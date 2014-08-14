# Copyright 2014 Sam Wilson <tecywiz121@gmail.com>
#
# This file is part of SketchWith.Us.
#
# SketchWith.Us is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# SketchWith.Us is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with SketchWith.Us.  If not, see <http://www.gnu.org/licenses/>.
import os
import logging
import redis
import gevent
import time
import json
import urlparse
from flask import Flask, render_template
from flask_sockets import Sockets
from werkzeug.datastructures import MultiDict
from peewee import *

REDIS_URL = os.environ['REDISCLOUD_URL']
REDIS_CHAN = 'sketch'

# Flask
app = Flask(__name__)
app.debug = 'DEBUG' in os.environ
app.debug = True

# Logging
file_handler = logging.StreamHandler()
app.logger.setLevel(logging.DEBUG)
app.logger.addHandler(file_handler)


# Flask Sockets
sockets = Sockets(app)

# Redis
redis = redis.from_url(REDIS_URL)

# Peewee
urlparse.uses_netloc.append('postgres')
db_url = urlparse.urlparse(os.environ['DATABASE_URL'])
db = PostgresqlDatabase(db_url.path[1:],
                        user=db_url.username,
                        password=db_url.password,
                        host=db_url.hostname,
                        port=db_url.port)

db.connect()

class BaseModel(Model):
    """The base class for all models"""
    class Meta:
        database = db

class Word(BaseModel):
    text = CharField(unique=True)
    plays = IntegerField(index=True)
    wins = IntegerField()

def get_next_word(used=None):
    # Fetch a random word that hasn't been used much
    subquery = Word.select(fn.Avg(Word.plays))
    result = (Word.select()
                .order_by(fn.Random())
                .where(Word.plays <= subquery))
    if used:
        result = result.where((Word.text << used) == False)
    result = result[0]

    # Update its play count
    query = Word.update(plays=Word.plays + 1).where(Word.id == result.id)
    query.execute()

    return result

app.logger.debug('Hello, World!')

class Message(object):
    """
    A message that was or will be sent over a WebSocket connection.
    """
    def __init__(self, verb, **kwargs):
        if isinstance(verb, Message):
            # Copy constructor - make a copy of the message.
            for k in dir(verb):
                if not k.startswith('_'):
                    setattr(self, k, getattr(verb, k))
        else:
            # Regular constructor
            self.verb = verb.upper()
            for k, v in kwargs.items():
                setattr(self, k, v)

    def _for_json(self):
        return dict((x, getattr(self, x)) for x in dir(self) if not x.startswith('_'))

def message_from_json(d):
    if 'verb' not in d:
        return d

    x = Message(d['verb'])
    for k, v in d.items():
        if not k.startswith('_'):
            setattr(x, k, v)
    return x

class MessageEncoder(json.JSONEncoder):
    def default(self, obj):
        if not hasattr(obj, '_for_json'):
            return super(json.JSONEncoder, self).default(obj)

        return obj._for_json()

def json_dumps(*args, **kwargs):
    kwargs['cls'] = MessageEncoder
    return json.dumps(*args, **kwargs)

def json_loads(*args, **kwargs):
    kwargs['object_hook'] = message_from_json
    return json.loads(*args, **kwargs)

class Player(object):
    """Represents a connection from a browser"""
    def __init__(self, manager, ws):
        self.manager = manager
        self.socket = ws
        self.last_message = time.time()
        self.alive = True
        self.table = None

    def _keepalive(self):
        """
        Sends a keepalive message if 30 seconds has passed since the last time
        this player was sent a message.
        """
        wait_for = 30                           # How long to sleep each loop
        while self.alive:
            gevent.sleep(wait_for)              # Wait until the next check
            now = time.time()
            delta = now - self.last_message
            if delta > 30:                      # More than 30 seconds?
                self._send_keepalive()          # Yes. Send a keepalive, and
                wait_for = 30                   # Wait another 30 seconds.
            else:
                wait_for = 30 - delta           # Nope, keep waiting.

    def _send_keepalive(self):
        """
        Sends a simple keepalive message to the player to make sure it's still
        there.
        """
        msg = Message('KEEPALIVE')
        try:
            self.send(msg)
        except:
            pass                                # Send takes care of disconnect

    def disconnect(self):
        """
        Closes the WebSocket and marks the player as dead.
        """
        self.alive = False
        self.socket.close()
        if self.table is not None:
            self.table.disconnect(self)

    def send(self, msg):
        """
        Sends a message to the player.
        """
        try:
            self.socket.send(json_dumps(msg))
            self.last_message = time.time()
        except:
            self.disconnect()
            raise

    def run(self):
        self.last_message = time.time()
        gevent.spawn(self._keepalive)
        while self.alive:
            gevent.sleep()

            app.logger.debug("Waiting for message")
            try:
                msg = self.socket.receive()
                app.logger.debug("Got Message: " + str(msg))
            except:
                self.disconnect()
                msg = None

            if msg:
                self.last_message = time.time()
                self._handle_message(msg)

    def _handle_message(self, msg):
        msg = json_loads(msg)
        if msg.verb == 'KEEPALIVE':
            return
        elif msg.verb == 'CONNECT':
            try:
                self.name = msg.player_name
            except AttributeError:
                logging.error('connect command missing player_name')
        elif msg.verb == 'JOIN':
            try:
                self.manager.find_table(msg.table).join(self)
            except AttributeError:
                logging.error('join command missing table')
                raise
        elif msg.verb == 'LEAVE':
            if self.table is None:
                logging.error('leave command with no table')
                return
            self.table.leave(self)
            self.table = None
        elif msg.verb == 'PASS':
            if self.table is None:
                logging.error('pass command with no table')
                return
            self.table.pass_turn(self)
        elif msg.verb == 'SKIP':
            if self.table is None:
                logging.error('skip command with no table')
                return
            self.table.skip_turn(self)

class Table(object):
    """A group of players"""
    def __init__(self, manager, name):
        self.name = name
        self.players = list()
        self.manager = manager
        self.pubsub = manager.pubsub
        self.topic = 'table.' + name
        self.players_key = '.'.join(['table', self.name, 'players'])
        self.turns_key = '.'.join(['table', self.name, 'turns'])
        self.word_key = '.'.join(['table', self.name, 'word'])
        self.skip_key = '.'.join(['table', self.name, 'skip'])

        # Subscribe to table updates
        kwargs = {self.topic: self._handle_message}
        self.pubsub.subscribe(**kwargs)

        # Set the initial starting word
        redis.setnx(self.word_key, get_next_word().text)

    def join(self, player):
        if player.table == self:
            return                              # Already part of this table.

        if player.table is not None:
            player.table.leave(player)          # Player has to leave old table

        msg = Message('JOINED')                 # Tell all the other players
        msg.player_name = player.name           # that a new player has joined.
        self.send(msg)

        player.table = self                     # Register the new player with
        self.players.append(player)             # this table.

        # Get a list of all the other players on this table
        others = redis.smembers(self.players_key)

        # Add new player to the player list
        redis.sadd(self.players_key, player.name)

        # Check if player in turn list
        rank = redis.zrank(self.turns_key, player.name)

        if rank is None:
            # Add player to the turn list if he/she wasn't already there
            redis.zadd(self.turns_key, player.name, time.time())

        # Prepare joined messages for all existing players
        msgs = []
        for other in others:
            if other == player.name:
                continue
            msg = Message('JOINED')
            msg.player_name = other
            msgs.append(msg)

        # Prepare passed message to set correct turn
        current = redis.zrange(self.turns_key, 0, 0)[0]
        msg = Message('PASSED', player_name=current)
        if player.name == current:
            msg.word = redis.get(self.word_key)
        msgs.append(msg)

        # Send all the prepared messages
        gevent.joinall([gevent.spawn(player.send, x) for x in msgs])

    def disconnect(self, player):
        """
        Causes a player to leave the table and disconnect from the server.
        """
        assert(player.table == self)
        if player.alive:
            player.disconnect()
        self._depart(player, True)

    def leave(self, player):
        """
        Causes a player to leave the table.
        """
        assert(player.table == self)
        self._depart(player, False)

    def skip_turn(self, player):
        """
        Causes a player to vote to skip the current artist. A majority is
        required.
        """

        # Make sure the artist isn't skipping
        artist = redis.zrange(self.turns_key, 0, 0)[0]
        if artist == player.name:
            app.logger.error('artist voted to skip')
            return

        # Add the player to the list of voted players
        redis.sadd(self.skip_key, player.name)

        voted = redis.scard(self.skip_key)
        total = redis.scard(self.players_key) - 1

        self.send(Message('SKIPPED', player_name=player.name))

        if voted * 2 > total:
            self._pass_turn(artist)

    def pass_turn(self, player):
        """
        If the given player is the active player, pass the turn to the next in
        line.
        """
        # Get the player's current rank
        rank = redis.zrank(self.turns_key, player.name)

        # Check if it is his/her turn
        if rank == 0:
            self._pass_turn(player.name)

    def _pass_turn(self, player_name):
        # Get the next player
        next_player = redis.zrange(self.turns_key, 1, 1)

        # Are we playing with ourself?
        if next_player:
            next_player = next_player[0]
        else:
            next_player = player_name

        # Set the new word
        word = redis.set(self.word_key, get_next_word().text)

        # Clear the skip key
        redis.delete(self.skip_key)

        # Tell everyone who's turn it is
        self.send(Message('PASSED', player_name=next_player))

        # Move the old player to the end of the turn list
        redis.zadd(self.turns_key, player_name, time.time())

    def send(self, msg):
        """
        Sends a message to all players connected to this table.
        """
        app.logger.debug("PUBLISH - " + self.topic + ": " + json_dumps(msg))
        redis.publish(self.topic, json_dumps(msg))

    def _depart(self, player, disconnected):
        """
        Removes a player from the table and updates all the other players.
        """
        self.players.remove(player)

        # If it is this player's turn, pass it automatically
        self.pass_turn(player)

        # Remove player from the player and turn lists
        redis.srem(self.players_key, player.name)
        redis.zrem(self.turns_key, player.name)

        msg = Message('DEPARTED')               # Let everyone know
        msg.player_name = player.name           # which player is leaving,
        msg.disconnected = disconnected         # and if they disconnected.
        self.send(msg)

        if not self.players:
            self.pubsub.unsubscribe(self.topic) # No players? Unsubscribe from
                                                # further updates.
            self.manager.remove_table(self.name)

    def _handle_message(self, msg):
        """
        Forwards messages from Redis to the players directly connected to this
        instance.
        """
        app.logger.debug(msg)
        if msg['type'] != 'message' or msg['channel'] != self.topic:
            return                              # Ignore messages we don't need

        msg = json_loads(msg['data'])
        for p in self.players:
            if msg.verb == 'PASSED' and msg.player_name == p.name:
                # Add the word to the passed message for the correct player
                special = Message(msg)
                special.word = redis.get(self.word_key)
                gevent.spawn(p.send, special)
            else:
                gevent.spawn(p.send, msg)


class SketchBackend(object):
    """
    Interface for registering and updating WebSocket players.
    """

    def __init__(self):
        self.tables = dict()
        self.pubsub = redis.pubsub()
        self.pubsub.subscribe(REDIS_CHAN)

    def __iter_messages(self):
        for msg in self.pubsub.listen():
            if msg['type'] == 'message':
                yield msg['data']

    def find_table(self, name):
        try:
            return self.tables[name]
        except KeyError:
            table = Table(self, name)
            self.tables[name] = table
            return table

    def remove_table(self, name):
        del self.tables[name]

    def run(self):
        """
        Listens for new messages in Redis.
        """
        for data in self.__iter_messages():
            pass

    def start(self):
        gevent.spawn(self.run)

sketches = SketchBackend()
sketches.start()

@app.route('/')
def index():
    return render_template('index.html')

@sockets.route('/game')
def game(ws):
    global sketches
    player = Player(sketches, ws)
    app.logger.debug('Running...')
    player.run()

if __name__ == '__main__':
    app.run()
