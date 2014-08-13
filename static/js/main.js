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

        this._enabled = false;

        var that = this;
        canvas.addEventListener('mouseup',
            function(evt) { return that._onmouseup(evt); });
        canvas.addEventListener('mousedown',
            function(evt) { return that._onmousedown(evt); });
        canvas.addEventListener('mousemove',
            function(evt) { that._onmousemove(evt); });
    };

    DrawingArea.prototype._getMouseCoords = function _getMouseCoords(evt) {
        var mouseX, mouseY;
        if (typeof(evt.offsetX) !== 'undefined') {
            mouseX = evt.offsetX;
            mouseY = evt.offsetY;
        } else if (typeof(evt.layerX) !== 'undefined') {
            mouseX = evt.layerX;
            mouseY = evt.layerY;
        }
        return [mouseX, mouseY];
    };

    DrawingArea.prototype._onmousedown = function _onmousedown(evt) {
        if (!this._enabled) { return; }
        var point = this._getMouseCoords(evt);
        this._path = [point];

        // TODO: Start a timer to report partial strokes
    };

    DrawingArea.prototype._onmouseup = function _onmouseup(evt) {
        if (!this._enabled) { return; }
        var point = this._getMouseCoords(evt);
        this._drawPoint(point[0], point[1]);

        if (this.onstroke) {
            this.onstroke(this._path);
        }
    };

    DrawingArea.prototype._onmousemove = function _onmousemove(evt) {
        if (!this._enabled) { return; }
        if (evt.buttons !== 1) {
            return;
        }

        var point = this._getMouseCoords(evt);
        this._drawPoint(point[0], point[1]);
    };

    DrawingArea.prototype._drawPoint = function _drawPoint(mouseX, mouseY) {
        var lastMouse = this._path[this._path.length - 1];
        this._ctx.beginPath();
        this._ctx.moveTo(lastMouse[0], lastMouse[1]);
        this._ctx.lineTo(mouseX, mouseY);
        this._ctx.stroke();
        this._path.push([mouseX, mouseY]);
    };

    DrawingArea.prototype.start = function start() { this._enabled = true; };
    DrawingArea.prototype.stop = function stop() { this._enabled = false; };

    var SketchTable = function SketchTable(target) {
        this._root = $(target);

        /* Initialize the drawing area */
        this._drawing = new DrawingArea(this._root.find('.the-canvas').get(0));
        this._drawing.onstroke = function(path) { console.log(path); };
    };

    SketchTable.prototype._log = function _log() {
        return console.log.apply(console, arguments);
    };

    SketchTable.prototype._send = function _send(obj) {
        this._log('Sending:', obj);
        this._socket.send(JSON.stringify(obj));
    };

    SketchTable.prototype._onopen = function _onopen(evt) {
        this._log('Connecting');

        /* Restablish State */
        if (typeof(this._player_name) !== 'undefined') {
            this._send({verb: 'CONNECT', player_name: this._player_name});
        }

        if (typeof(this._table) !== 'undefined') {
            this.join(this._table);
        }
    };

    SketchTable.prototype._onmessage = function _onmessage(evt) {
        this._log(evt);
    };

    SketchTable.prototype.login = function login(to, player_name) {
        this._url = to;
        this._player_name = player_name;

        var ws = new ReconnectingWebSocket(this._url);

        var that = this;
        ws.onopen = function(evt) { that._onopen(evt); };
        ws.onmessage = function(evt) { that._onmessage(evt); };

        this._socket = ws;
    };

    SketchTable.prototype.join = function join(table) {
        this._table = table;

        this._send({verb: 'JOIN', table: table});
    };

    SketchTable.prototype.leave = function leave() {
        delete this._table;
        this._send({verb: 'LEAVE'});
    };

    SketchTable.prototype.pass = function pass() {
        this._send({verb: 'PASS'});
    };

    global.SketchTable = SketchTable;
}(this));

$(function() {
    'use strict';

});
