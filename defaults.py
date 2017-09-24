#!/usr/bin/env python3

import datetime

# Tournament Name - Used in email communications and headers
TOURNAMENTNAME = "{0} Tournament".format(datetime.date.today().strftime('%Y'))

# DB
#  DBFILE is the name of the file that contains the scores and player database.
DBFILE = "scores.db"
DBBACKUPS = "backups"
DBDATEFORMAT = "%Y-%m-%d-%H-%M-%S"

# PREFERENCES
DEFAULTCUTSIZE = 32
#   LINKVALIDDAYS is the number of days links for invitations and
#   password resets should remain valid.  They expire after LINKVALIDDAYS
#   has passed.
LINKVALIDDAYS = 7

# EMAIL
#   These settings are for the outbound email server that sends invites
#   and password reset links to users.
EMAILSERVER = "smtp.server.com"
EMAILPORT = 587
EMAILUSER = "email@address.com"
EMAILFROM = "{0} <{1}>".format("Tournament Mahjong", EMAILUSER)
EMAILPASSWORD = ""
