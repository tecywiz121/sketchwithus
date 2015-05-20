/*
 * Copyright 2014 Sam Wilson <tecywiz121@gmail.com>
 *
 * This file is part of SketchWith.Us.
 *
 * SketchWith.Us is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * SketchWith.Us is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with SketchWith.Us.  If not, see <http://www.gnu.org/licenses/>.
 */
(function(global) {
    'use strict';

    var DrawingArea = function DrawingArea(canvas) {
        this._canvas = canvas;
        this._ctx = canvas.getContext('2d');
        this._window = [];

        this._enabled = false;
        this._antiscroll = false;

        var that = this;
        canvas.addEventListener('mouseup',
            function(evt) { return that._onmouseup(evt); });
        canvas.addEventListener('mouseleave',
            function(evt) { return that._onmouseleave(evt); });
        canvas.addEventListener('mousedown',
            function(evt) { return that._onmousedown(evt); });
        canvas.addEventListener('mousemove',
            function(evt) { that._onmousemove(evt); });
        document.addEventListener('touchstart',
            function(evt) { return that._ontouchstart(evt); });
        document.addEventListener('touchmove',
            function(evt) { return that._ontouchmove(evt); });
        document.addEventListener('touchend',
            function(evt) { return that._ontouchend(evt); });
        document.addEventListener('touchcancel',
            function(evt) { return that._ontouchend(evt); });
    };

    DrawingArea.prototype._getMouseCoords = function _getMouseCoords(evt) {
        var mouseX, mouseY;
        var $canvas = $(this._canvas);
        if (typeof(evt.offsetX) !== 'undefined') {
            mouseX = evt.offsetX;
            mouseY = evt.offsetY;
        } else if (typeof(evt.layerX) !== 'undefined') {
            mouseX = evt.layerX;
            mouseY = evt.layerY;
        } else if (typeof(evt.pageX) !== 'undefined') {
            var offset = $canvas.offset();
            mouseX = evt.pageX - offset.left;
            mouseY = evt.pageY - offset.top;
        }

        var realW = $canvas.width(),
            realH = $canvas.height(),
            attrW = $canvas.attr('width'),
            attrH = $canvas.attr('height');

        var xRatio = attrW / realW,
            yRatio = attrH / realH;

        this._window.push([Math.floor(mouseX * xRatio), Math.floor(mouseY * yRatio)]);

        var x = 0, y = 0;
        var len = this._window.length;
        for (var ii = 0; ii < len; ii++) {
            x += this._window[ii][0];
            y += this._window[ii][1];
        }

        if (len >= 5) {
            this._window = this._window.slice(-5);
        }

        return [x/len, y/len];
    };

    DrawingArea.prototype._onmousedown = function _onmousedown(evt) {
        if (!this._enabled) { return; }
        var point = this._getMouseCoords(evt);
        this._path = [point];
        this._setSendInterval();
    };

    DrawingArea.prototype._onmouseup = function _onmouseup(evt) {
        if (!this._enabled) { return; }
        var point = this._getMouseCoords(evt);
        this._drawPoint(point[0], point[1]);
        this._clearSendInterval();
        this._window = [];

        if (this.onstroke) {
            this.onstroke(this._path);
        }
    };

    DrawingArea.prototype._onmouseleave = function _onmouseleave(evt) {
        var btns;
        if ('buttons' in evt) {
            /* FF, IE */
            btns = evt.buttons;
        } else {
            /* Chrome */
            btns = evt.which;
        }
        this._clearSendInterval();
        this._window = [];
        if (this._enabled && btns === 1 && this.onstroke) {
            this.onstroke(this._path);
            this._path = [this._path[this._path.length - 1]];
        }
    };

    DrawingArea.prototype._onmousemove = function _onmousemove(evt) {
        if (!this._enabled) { return; }
        if ('buttons' in evt && evt.buttons !== 1) {
            /* FF, IE */
            this._clearSendInterval();
            return;
        } else if (evt.which !== 1) {
            /* Chrome */
            this._clearSendInterval();
            return;
        }

        this._setSendInterval();
        var point = this._getMouseCoords(evt);
        this._drawPoint(point[0], point[1]);
    };

    DrawingArea.prototype._ontouchstart = function _ontouchstart(evt) {
        if (this._canvas == evt.target) {
            evt.preventDefault();
            if (!this._antiscroll) {
                this._antiscroll = true;
                this._onmousedown({pageX: evt.targetTouches[0].pageX,
                                    pageY: evt.targetTouches[0].pageY});
            }
        }
    };

    DrawingArea.prototype._ontouchmove = function _ontouchmove(evt) {
        if (this._antiscroll) {
            evt.preventDefault();
            evt.targetTouches[0].buttons = 1;
            var fakeEvent = {
                buttons: 1,
                which: 1,
                pageX: evt.targetTouches[0].pageX,
                pageY: evt.targetTouches[0].pageY
            };
            this._onmousemove(fakeEvent);
        }
    };

    DrawingArea.prototype._ontouchend = function _ontouchend(evt) {
        if (this._antiscroll) {
            evt.preventDefault();
            this._antiscroll = false;
            this._onmouseup({pageX: evt.changedTouches[0].pageX,
                                pageY: evt.changedTouches[0].pageY});
        }
    };

    DrawingArea.prototype._drawPoint = function _drawPoint(mouseX, mouseY) {
        var lastMouse = this._path[this._path.length - 1];
        this._ctx.beginPath();
        this._ctx.moveTo(lastMouse[0], lastMouse[1]);
        this._ctx.lineTo(mouseX, mouseY);
        this._ctx.stroke();
        this._path.push([mouseX, mouseY]);
    };

    DrawingArea.prototype._setSendInterval = function _setSendInterval() {
        var that = this;
        if (typeof(this._interval) === 'undefined') {
            this._interval = setInterval(function() { that._sendStrokes(that); }, 75);
        }
    };

    DrawingArea.prototype._clearSendInterval = function _clearSendInterval() {
        if (this._interval) {
            clearInterval(this._interval);
            this._interval = undefined;
        }
    };

    DrawingArea.prototype._sendStrokes = function _sendStrokes(area) {
        if (area._path.length < 2) {
            return;
        }

        if (area.onstroke) {
            area.onstroke(area._path);
        }
        area._path = [area._path[area._path.length-1]];
    };

    DrawingArea.prototype.start = function start() { this._enabled = true; };
    DrawingArea.prototype.stop = function stop() { this._enabled = false; };

    DrawingArea.prototype.clear = function clear() {
        this._ctx.clearRect(0, 0, this._canvas.width, this._canvas.height);
        this._path = [];
    };

    DrawingArea.prototype.draw = function draw(points) {
        this._ctx.beginPath();
        this._ctx.moveTo(points[0][0], points[0][1]);
        for (var ii = 1; ii < points.length; ii++) {
            this._ctx.lineTo(points[ii][0], points[ii][1]);
        }
        this._ctx.stroke();
    };

    var SketchTableLog = function SketchTableLog(target) {
        this._el = $(target);
        this._scroll = this._el.parent('.tab-content');
    };

    SketchTableLog.prototype.chat = function chat(username, msg) {
        var $user = $('<span class="chat-user" />').text(username),
            $msg = $('<span class="chat-message" />').text(msg),
            $div = $('<div class="chat-entry message" />').append($user, $msg);

        this._write($div);
    };

    SketchTableLog.prototype.control = function control(msg) {
        var $msg = $('<span class="chat-message" />').text(msg),
            $div = $('<div class="chat-entry control" />').append($msg);
        this._write($div);
    };

    SketchTableLog.prototype._write = function _write(element) {
        this._el.append(element);

        if (this._el.is('.active')) {
            this._scroll.animate({ scrollTop: this._el.height() }, 'slow');
        }
    };

    var PlayerList = function PlayerList(chatLog, target) {
        this._el = $(target);
        this._chat = chatLog;
        this._players = {};
    };

    PlayerList.prototype.joined = function joined(player) {
        this._chat.control(player + ' has joined the table');

        if (!(player in this._players)) {
            var $score = $('<span class="pull-right score">'),
                $li = $('<li class="player">').text(player).append($score);

            this._players[player] = $li;
            this._el.append($li);
        }
    };

    PlayerList.prototype.reset = function reset(player, r) {
        this._el.find('.score').text('');
    };

    PlayerList.prototype.score = function score(player, s) {
        var $player = this._players[player];
        if (!$player) {
            this.joined(player);
            $player = this._players[player];
        }
        $player.find('.score').text(s);
    };

    PlayerList.prototype.departed = function departed(player, disconnected) {
        if (disconnected) {
            this._chat.control(player + ' has disconnected');
        } else {
            this._chat.control(player + ' has left the table');
        }

        var $li = this._players[player];
        delete this._players[player];
        $li.remove();
    };

    PlayerList.prototype.clear = function clear() {
        var x = this._players;
        this._players = {};
        for (var key in x) {
            x[key].remove();
        }
    };

    var SketchTable = function SketchTable(target) {
        this._root = $(target);
        this._guess_form = this._root.find('.guess-form');
        this._draw_controls = this._root.find('.draw-controls');
        this._draw_word = this._draw_controls.find('.canvas-word');
        this._btn_guess = this._guess_form.find('.canvas-guess');
        this._btn_skip = this._guess_form.find('.canvas-skip');
        this._btn_pass = this._draw_controls.find('.canvas-pass');
        this._txt_guess = this._guess_form.find('.guess-input');
        this._timer = this._root.find('.time-remaining');
        this._myTurn = false;

        /* Set up skip/pass buttons */
        var that = this;
        this._btn_pass.click(function(evt) { return that._onpass(evt); });
        this._guess_form.submit(function(evt) { return that._onguess(evt); });
        this._btn_guess.click(function(evt) { return that._onguess(evt); });
        this._btn_skip.click(function(evt) { return that._onskip(evt); });

        /* Initialize the drawing area */
        this._drawing = new DrawingArea(this._root.find('.the-canvas').get(0));
        this._drawing.onstroke = function(path) { that._onstroke(path); };

        /* Initialize the chat log */
        this._chat = new SketchTableLog(this._root.find('.chat-log'));

        /* Initialize the players list */
        this._players = new PlayerList(this._chat,
                                        this._root.find('.player-list'));

        /* Start the timer updater */
        setInterval(function() { that._update_timer(); }, 500);
    };

    SketchTable.prototype._update_timer = function _update_timer() {
        var now = Date.now(),
            diff = Math.floor((this._end_time - now) / 1000);

        diff -= 3;  /* 3 seconds of buffer time to hide lag */
        if (diff < 0) { diff = 0; }

        if (isNaN(diff)) {
            this._timer.text('');
        } else {
            this._timer.text(diff + 's');
        }
    };

    SketchTable.prototype._onstroke = function _onstroke(path) {
        this._send({verb: 'DRAW', points: path});
    };

    SketchTable.prototype._onpass = function _onpass(evt) {
        this.pass();
        return false;
    };

    SketchTable.prototype._onguess = function _onguess(evt) {
        var word = this._txt_guess.val();
        if (word.length > 0) {
            this.guess(this._txt_guess.val());
            this._txt_guess.val('');
        }
        return false;
    };

    SketchTable.prototype._onskip = function _onskip(evt) {
        this._send({verb: 'SKIP'});
        return false;
    };

    SketchTable.prototype._log = function _log() {
        //return console.log.apply(console, arguments);
    };

    SketchTable.prototype._send = function _send(obj) {
        this._log('Sending:', obj);
        this._socket.send(JSON.stringify(obj));
    };

    SketchTable.prototype._onclose = function _onclose(evt) {
        this._log('Disconnected');
        this._chat.control('Disconnected');
    };

    SketchTable.prototype._onopen = function _onopen(evt) {
        this._log('Connecting');
        this._players.clear();

        /* Restablish State */
        if (typeof(this._player_name) !== 'undefined') {
            this._chat.control('Registering as ' + this._player_name);
            this._send({verb: 'CONNECT', player_name: this._player_name});
        }

        if (typeof(this._table) !== 'undefined') {
            this.join(this._table);
        }
    };

    SketchTable.prototype._onmessage = function _onmessage(evt) {
        var that = this;
        if (typeof(evt.data) === 'string') {
            this._processMessage(evt.data);
        } else {
            var f = new FileReader();
            f.addEventListener('loadend',
                function() { that._processMessage(f.result); });
            f.readAsText(evt.data);
        }
    };

    SketchTable.prototype._processMessage = function _processMessage(text) {
        var obj;
        try {
            obj = JSON.parse(text);
            this._log(obj);
        } catch (e) {
            this._log('Error while parsing JSON:', e);
            this._log(text);
            return;
        }

        switch (obj.verb.toUpperCase()) {
        case 'KEEPALIVE':
            break;
        case 'JOINED':
            this._players.joined(obj.player_name);
            break;
        case 'DEPARTED':
            this._players.departed(obj.player_name, obj.disconnected);
            break;
        case 'PASSED':
            this._passed(obj.player_name, obj.word, obj.guesser, obj.score,
                            obj.end_time);
            break;
        case 'SKIPPED':
            this._skipped(obj.player_name);
            break;
        case 'DRAWN':
            if (!this._myTurn) {
                this._drawing.draw(obj.points);
            }
            break;
        case 'GUESSED':
            this._guessed(obj.player_name, obj.word, obj.correct);
            break;
        case 'WON':
            this._won(obj.player_name);
            break;
        case 'ENDED':
            this._ended();
            break;
        }
    };

    SketchTable.prototype._won = function _won(player_name) {
        this._chat.control(player_name + ' won the match!');
        this._players.reset();
    };

    SketchTable.prototype._ended = function _ended() {
        this._chat.control('You took too long! No one wins this game.');
    };

    SketchTable.prototype.login = function login(to, player_name) {
        this._url = to;
        this._player_name = player_name;

        var ws = new ReconnectingWebSocket(this._url);

        var that = this;
        ws.onopen = function(evt) { that._onopen(evt); };
        ws.onclose = function(evt) { that._onclose(evt); };
        ws.onmessage = function(evt) { that._onmessage(evt); };

        this._socket = ws;
    };

    SketchTable.prototype.join = function join(table) {
        this._table = table;

        if (this._socket.readyState === WebSocket.OPEN) {
            this._chat.control('Joining table ' + table);
            this._send({verb: 'JOIN', table: table});

            if (typeof(history.replaceState) !== 'undefined') {
                history.replaceState(null, 'SketchWith.Us: ' + table,
                                        '/' + table);
            }
        }
    };

    SketchTable.prototype.leave = function leave() {
        delete this._table;
        this._send({verb: 'LEAVE'});
        this._players.clear();
    };

    SketchTable.prototype.guess = function guess(word) {
        this._send({verb: 'GUESS', word: word});
    };

    SketchTable.prototype.pass = function pass() {
        this._send({verb: 'PASS'});
    };

    SketchTable.prototype._guessed = function _guessed(player_name, word,
        correct) {
        var msg = player_name;

        if (correct) {
            msg += ' correctly';
        }

        msg += ' guessed \u201C' + word + '\u201D';

        this._chat.control(msg);
    };

    SketchTable.prototype._skipped = function _skipped(player_name, word) {
        this._chat.control(player_name + ' voted to skip');
    };

    SketchTable.prototype._passed = function _passed(player_name, word,
                                                        guesser, score,
                                                        end_time) {
        // Print the active player in the log
        var possessive = player_name + "'s";
        if (player_name.slice(-1) === 's') {
            possessive = player_name + "'";
        }
        this._chat.control('It is ' + possessive + ' turn');

        if (typeof(score) !== 'undefined') {
            this._players.score(guesser, score);
        }

        // Clear the drawing area
        this._drawing.clear();

        if (this._player_name === player_name && typeof(word) !== 'undefined') {
            // If we're the active player, enable drawing.
            this._drawing.start();

            this._draw_word.text(word);

            this._guess_form.hide();
            this._draw_controls.show();

            this._myTurn = true;
        } else {
            // If we're not the active player, disable everything.
            this._drawing.stop();

            this._draw_controls.hide();
            this._guess_form.show();

            this._myTurn = false;
        }

        this._end_time = 1000 * parseFloat(end_time);
    };

    global.SketchTable = SketchTable;
}(this));

$(function() {
    'use strict';

    function fullscreen(element) {
        if (element.requestFullscreen) {
            element.requestFullscreen();
        } else if (element.mozRequestFullScreen) {
            element.mozRequestFullScreen();
        } else if (element.webkitRequestFullscreen) {
            element.webkitRequestFullscreen();
        } else if (element.msRequestFullscreen) {
            element.msRequestFullscreen();
        }
    }

    var $modal = $('#login-modal'),
        $btn = $('#login-button'),
        $name = $('#login-form-name'),
        $table = $('#login-form-table');

    var game = new SketchTable('.sketch-row');

    $btn.click(function(e) {
        var name = $name.val(),
            table = $table.val();

        var good = true;

        /* Check for valid inputs */
        if (name.length > 0) {
            $name.parent('.form-group').removeClass('has-error');
        } else {
            $name.parent('.form-group').addClass('has-error');
            good = false;
        }

        if (table.length > 0) {
            $table.parent('.form-group').removeClass('has-error');
        } else {
            $table.parent('.form-group').addClass('has-error');
            good = false;
        }

        if (!good) {
            return false;
        }
        $modal.modal('hide');

        /* Get the WebSocket path */
        var loc = window.location, new_uri;
        if (loc.protocol === 'https') {
            new_uri = 'wss';
        } else {
            new_uri = 'ws';
        }

        new_uri += '://' + loc.host + '/game';

        /* Fullscreen if on a tiny screen */
        if (screen.width < 760 || screen.height < 760) {
            fullscreen(document.documentElement);
        }

        /* Perform the login and join */
        game.login(new_uri, name);
        game.join(table);
        return false;
    });

    $modal.modal({
        backdrop: 'static',
        keyboard: false});

    window.temp = game;
});
