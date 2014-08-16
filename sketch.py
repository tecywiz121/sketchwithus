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
from flask import Flask, render_template
from flask_sockets import Sockets
from werkzeug.datastructures import MultiDict
from models import db, Word
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

db.connect()

def get_next_word(used=None):
    try:
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
    except:
        db.rollback()
        raise

def word_won(word):
    try:
        query = Word.update(wins=Word.wins + 1).where(Word.text == word)
        query.execute()
    except:
        db.rollback()
        raise

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
        elif msg.verb == 'DRAW':
            if self.table is None:
                logging.error('draw command with no table')
                return
            self.table.draw(self, msg.points);
        elif msg.verb == 'GUESS':
            if self.table is None:
                logging.error('guess command with no table')
                return
            self.table.guess(self, msg.word)

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
        self.end_key = '.'.join(['table', self.name, 'end'])
        self.alive = True

        # Subscribe to table updates
        kwargs = {self.topic: self._handle_message}
        self.pubsub.subscribe(**kwargs)

        # Set the initial starting word
        redis.setnx(self.word_key, get_next_word().text)

        # Start the game end loop
        gevent.spawn(self._end_game)

    def guess(self, player, guess):
        """
        Guess a word.
        """
        artist_name = self._get_artist()
        if player.name == artist_name:
            app.logger.error('artist submitted a guess')
            return

        self.send(Message('GUESSED', player_name=player.name, word=guess))

    def draw(self, player, points):
        """
        Draws the specified points on the canvas.
        """
        artist_name = self._get_artist()

        if player.name != artist_name:
            app.logger.error('player drawing when not the artist')
            return

        self.send(Message('DRAWN', points=points))

    def _get_artist(self):
        try:
            return redis.zrange(self.turns_key, 0, 0)[0]
        except IndexError:
            return None

    def _has_artist(self, artist=None):
        if artist is None:
            artist = self._get_artist()
        return any(x.name == artist for x in self.players)

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
        others = redis.zrange(self.players_key, 0, -1)

        # Check if the player exists (race condition I guess)
        score = redis.zscore(self.players_key, player.name)
        if score is None:
            # Add new player to the player list
            redis.zadd(self.players_key, player.name, 0)

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
        current = self._get_artist()
        msg = Message('PASSED', player_name=current)
        if player.name == current:
            msg.word = redis.get(self.word_key)

            end_time = time.time() + 120
            if not redis.setnx(self.end_key, end_time):
                # Clock's already started!
                end_time = redis.get(self.end_key)
        else:
            end_time = redis.get(self.end_key)
            assert(end_time is not None)
        msg.end_time = end_time
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
        artist = self._get_artist()
        if artist == player.name:
            app.logger.error('artist voted to skip')
            return

        # Add the player to the list of voted players
        redis.sadd(self.skip_key, player.name)

        self.send(Message('SKIPPED', player_name=player.name))

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

    def _pass_turn(self, player_name, guesser=None, score=None):
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
        msg = Message('PASSED', player_name=next_player)
        msg.end_time = time.time() + 120
        redis.set(self.end_key, msg.end_time)
        if score is not None:
            msg.guesser = guesser
            msg.score = score
        self.send(msg)

        # Ten points to win the game
        if score >= 10:
            # Send the won message
            self.send(Message('WON', player_name=guesser))

            # Clear all scores
            players = redis.zrange(self.players_key, 0, -1)
            scores = dict((x, 0) for x in players)
            redis.zadd(self.players_key, **scores)

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

        msg = Message('DEPARTED')               # Let everyone know
        msg.player_name = player.name           # which player is leaving,
        msg.disconnected = disconnected         # and if they disconnected.
        self.send(msg)

        # The only time DEPART causes a turn to shift is when the current
        # artist leaves. The instance that receives the DEPART will always have
        # the departing player. Therefore it is safe to do the _pass_turn call
        # here.
        artist = self._get_artist()
        if player.name == artist:
            self._pass_turn(player.name)

        # Remove player from the player and turn lists
        redis.zrem(self.players_key, player.name)
        redis.zrem(self.turns_key, player.name)

        if not self.players:
            self.pubsub.unsubscribe(self.topic) # No players? Unsubscribe from
                                                # further updates.
            self.manager.remove_table(self.name)
            self.alive = False

    def _end_game(self):
        while self.alive:
            try:
                end_time = float(redis.get(self.end_key))
            except TypeError:
                gevent.sleep(1)
                continue

            now = time.time()
            if end_time < now:
                self._terminate_game()
            else:
                gevent.sleep((end_time-now)/2)

    def _terminate_game(self):
        if self._has_artist():
            redis.delete(self.end_key)
            self.send(Message('ENDED', player_name=self._get_artist()))

    def _handle_message(self, msg):
        """
        Forwards messages from Redis to the players directly connected to this
        instance.
        """
        app.logger.debug('RECEIVED - ' + str(msg))
        if msg['type'] != 'message' or msg['channel'] != self.topic:
            return                              # Ignore messages we don't need

        msg = json_loads(msg['data'])

        # If we have the artist, we're responsible for adjusting game state
        must_pass = False
        artist = self._get_artist()
        score = None
        guesser = None
        if self._has_artist(artist):
            if msg.verb == 'GUESSED':
                if msg.player_name == artist:
                    app.logger.log('artist submitted a guess')
                else:
                    word = redis.get(self.word_key)
                    # TODO: Correct is only set for clients connected to this instance.
                    msg.correct = word.lower() == msg.word.lower()
                    if msg.correct:
                        guesser = msg.player_name
                        score = redis.zincrby(self.players_key, msg.player_name, 1)
                        word_won(word)
                        must_pass = True
            elif msg.verb == 'SKIPPED':
                if msg.player_name == artist:
                    app.logger.log('artist voted to skip')
                else:
                    voted = redis.scard(self.skip_key)
                    total = redis.zcard(self.players_key) - 1

                    if voted * 2 > total:
                        must_pass = True
            elif msg.verb == 'ENDED':
                if msg.player_name == artist:
                    must_pass = True
                # TODO: Player name will be sent on other instances
                del msg.player_name

        # Repeat the message to all players
        for p in self.players:
            if msg.verb == 'PASSED' and msg.player_name == p.name:
                # Add the word to the passed message for the correct player
                special = Message(msg)
                special.word = redis.get(self.word_key)
                gevent.spawn(p.send, special)
            else:
                gevent.spawn(p.send, msg)

        if must_pass:
            self._pass_turn(artist, guesser=guesser, score=score)

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

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def index(path):
    return render_template('index.html', path=path)

@sockets.route('/game')
def game(ws):
    global sketches
    player = Player(sketches, ws)
    app.logger.debug('Running...')
    player.run()

if __name__ == '__main__':
    app.run()
