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
from peewee import *
import os
import urlparse

urlparse.uses_netloc.append('postgres')
db_url = urlparse.urlparse(os.environ['DATABASE_URL'])
db = PostgresqlDatabase(db_url.path[1:],
                        user=db_url.username,
                        password=db_url.password,
                        host=db_url.hostname,
                        port=db_url.port)

class BaseModel(Model):
    """The base class for all models"""
    class Meta:
        database = db

class Word(BaseModel):
    text = CharField(unique=True)
    plays = IntegerField(index=True)
    wins = IntegerField()
