#!/usr/bin/env python2
#
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
from itertools import islice
from peewee import *
import sys

try:
    from models import db, Word
except KeyError:
    raise Exception('Expects a postgres URL in DATABASE_URL environment variable')

def _grouper(n, iterable):
    it = iter(iterable)
    while True:
        chunk = tuple(islice(it, n))
        if not chunk:
            return
        yield chunk

def _file_iter(path):
    """
    Reads a file line by line and filters out empty lines.
    """
    with open(path, 'rU') as f:
        for line in f:
            line = line.strip().lower()
            if not line:
                continue
            yield line

def _calculate_ratios(args):
    """
    Calculates the ratios between words given some fixed points.
    """
    # Calculate ratios of parts of speech to generate
    ratios = {'nouns': args.nouns,
                'verbs': args.verbs,
                'adjectives': args.adjectives,
                'adverbs': args.adverbs}

    free = sum(1 for v in ratios.values() if v is None)
    used = sum(v for v in ratios.values() if v is not None)

    free = (1.0 - used) / free

    # Convert to absolute numbers
    for k,v in ratios.items():
        if v is None:
            v = free
        ratios[k] = int(v * args.number)

    # Make sure we have exactly the right number of words
    ratios['nouns'] += args.number - sum(ratios.values())

    return ratios

def main():
    # Parse command line
    import argparse
    parser = argparse.ArgumentParser(description='Add words to the SketchWithUs database')
    parser.add_argument('input', help='file containing one word per line')
    args = parser.parse_args()

    # Connect to the database
    db.connect()

    # Insert all the words
    with db.transaction():
        for chunk in _grouper(1000, _file_iter(args.input)):
            print chunk
            Word.insert_many({'text': x, 'plays': 0, 'wins': 0} for x in chunk).execute()


if __name__ == '__main__':
    main()
