#!/usr/bin/env python3

__doc__ = """
Main program to run a web server for WRC tournament software
Launch this program (with an optional port number argument) on the
web server after configuring the mysettings.py file.  If no scores
database is found, an empty one will be created.  The first user
account will be given admin privileges to configure other options.
The web log is written to standard output (redirect as desired).
"""

import sys
import os.path
import os
import math
import tornado.httpserver
import tornado.ioloop
import tornado.options
import tornado.web
import tornado.template
import signal
import json
import datetime

from quemail import QueMail
import handler
import util
import db
import settings

import home
import login
import seating
import scores
import leaderboard
import players
import playerstats
import tournament
import spreadsheet
import preferences
import admin

# import and define tornado-y things
from tornado.options import define, options
cookie_secret = util.randString(32)

class MainHandler(handler.BaseHandler):
    def get(self):
        no_user = False
        with db.getCur() as cur:
            cur.execute("SELECT COUNT(*) FROM Users")
            no_user = cur.fetchone()[0] == 0
            tournaments = []

        self.render("index.html", no_user = no_user, tournaments = tournaments)

class Application(tornado.web.Application):
    def __init__(self, force=False, verbose=0):
        db.init(force=force, verbose=verbose)

        if getattr(sys, 'frozen', False):
            curdirname = os.path.dirname(sys.executable)
        else:
            curdirname = os.path.dirname(os.path.realpath(__file__))

        handlers = [
            (r"/", home.TournamentHomeHandler),
            (r"/authentication", handler.AuthenticationHandler),
            (r"/tournaments", tournament.TournamentsHandler),
            (r"/tournamentList", tournament.TournamentListHandler),
            (r"/updatePlayerRole", tournament.TournamentPlayerHandler),
            (r"/edittournament", tournament.EditTournamentHandler),
            (r"/edittournament/([^/]+)", tournament.EditTournamentHandler),
            (r"/countries", tournament.CountriesHandler),
            (r"/update[Cc]ountries", tournament.UpdateCountriesHandler),
            (r"/algorithms", seating.AlgorithmsHandler),
            (r"/orderings", seating.OrderingsHandler),
            (r"/t/([^/]*)/tournament", tournament.TournamentHandler),
            (r"/t/([^/]*)/players", tournament.TournamentPlayersAjaxHandler),
            (r"/t/([^/]*)/players.html", tournament.TournamentPlayersHandler),
            (r"/t/([^/]*)/tournament.xlsx", 
             spreadsheet.DownloadTournamentSheetHandler),
            (r"/t/([^/]*)/deleteplayer", tournament.DeletePlayerHandler),
            (r"/t/([^/]*)/addround", tournament.AddRoundHandler),
            (r"/t/([^/]*)/deleteround", tournament.DeleteRoundHandler),
            (r"/t/([^/]*)/settings", tournament.SettingsHandler),
            (r"/t/([^/]*)/roundsettings.html", tournament.ShowSettingsHandler),
            (r"/t/([^/]*)/tourney", tournament.TourneySettingsAjaxHandler),
            (r"/t/([^/]*)/tourney.html", tournament.TourneySettingsHandler),
            (r"/t/([^/]*)/associations", tournament.AssociationsHandler),
            (r"/t/([^/]*)/seating", seating.SeatingHandler),
            (r"/t/([^/]*)/swapseating", seating.SwapSeatingHandler),
            (r"/t/([^/]*)/seating.html", seating.ShowSeatingHandler),
            (r"/t/([^/]*)/seating.csv", seating.SeatingCsvHandler),
            (r"/t/([^/]*)/leaderboard", leaderboard.LeaderDataHandler),
            (r"/t/([^/]*)/leaderboard.html", leaderboard.LeaderboardHandler),
            (r"/players(.*)", players.PlayersHandler),
            (r"/playerlist", players.PlayerListHandler),
            (r"/mergePlayers/", players.MergePlayersHandler),
            (r"/findPlayersInSpreadsheet", 
             spreadsheet.FindPlayersInSpreadsheetHandler),
            (r"/uploadplayers", spreadsheet.UploadPlayersHandler),
            (r"/playerStats/(.*)", playerstats.PlayerStatsHandler),
            (r"/playerStatsData/(.*)", playerstats.PlayerStatsDataHandler),
            (r"/t/([^/]*)/scores", scores.EditGameHandler),
            (r"/t/([^/]*)/penalties", scores.EditPenaltiesHandler),
            (r"/t/([^/]*)/penalties/(\d+)", scores.EditPenaltiesHandler),
            (r"/users.html", admin.ManageUsersHandler),
            (r"/invites/([^/]+)", admin.ManageInvitesHandler),
            (r"/setup", login.SetupHandler),
            (r"/login", login.LoginHandler),
            (r"/logout", login.LogoutHandler),
            (r"/preferences", preferences.PreferencesHandler),
            (r"/invite", login.InviteHandler),
            (r"/verify/([^/]+)", login.VerifyHandler),
            (r"/reset", login.ResetPasswordHandler),
            (r"/reset/([^/]+)", login.ResetPasswordLinkHandler),
        ]
        app_settings = dict(
            template_path = os.path.join(curdirname, "templates"),
            static_path = os.path.join(curdirname, "static"),
            debug = True,
            cookie_secret = cookie_secret,
            login_url = "/login"
        )
        tornado.web.Application.__init__(self, handlers, **app_settings)

def periodicCleanup():
    with db.getCur() as cur:
        cur.execute("DELETE FROM VerifyLinks WHERE Expires <= datetime('now')")

def main():
    default_socket = "/tmp/tomas.sock"
    socket = None
    force = False
    i = 1
    errors = []
    usage = """
usage: {prog} [-f|--force] [tornado-options] [Port|Socket]
positional arguments:
  Port|Socket   Port number or unix socket to listen on
                (default: {port})
optional arguments:
  -f|--force    Force database schema updates without prompting
                (default: {force})
  -h|--help     show help information and exit
  -v|--verbose  Add verbosity in messages about database and SMTP

tornado options:
""".format(prog=os.path.basename(sys.argv[0]), port=default_socket, force=force)
    usage = __doc__ + usage
    verbose = 0
    while i < len(sys.argv):
        if sys.argv[i].isdigit():
            if socket is None:
                socket = int(sys.argv[i])
            else:
                errors.append('Multiple port or socket arguments specified '
                              '"{0}"'.format(sys.argv[i]))
        elif sys.argv[i].startswith('-'):
            if sys.argv[i] in ['-f', '--force']:
                force = True
                del sys.argv[i]
                continue
            elif sys.argv[i] in ['-h', '--help']:
                print(usage)  # and don't exit so tornado help will print
                if sys.argv[i] == '-h':
                    sys.argv[i] = '--help' # tornado doesn't accept -h option
            elif sys.argv[i] in ['-v', '--verbose']:
                verbose += 1
                del sys.argv[i]
                continue
            else:
                pass  # Leave tornado options in place for later parsing
        else:
            if socket is None:
                socket = sys.argv[i]
            else:
                errors.append('Multiple port or socket arguments specified '
                              '"{0}"'.format(sys.argv[i]))
        i += 1

    if socket is None:
        socket = default_socket

    tornado.options.parse_command_line()
    if errors:
        print("\n  ".join(["Errors:"] + errors))
        sys.exit(-1)

    if hasattr(settings, 'EMAILSERVER'):
        qm = QueMail.get_instance()
        qm.init(settings.EMAILSERVER, settings.EMAILUSER,
                settings.EMAILPASSWORD, settings.EMAILPORT, use_tls=True,
                debug_level=min(verbose, 2))
        qm.start()

    http_server = tornado.httpserver.HTTPServer(
        Application(force=force, verbose=verbose),
        max_buffer_size=24*1024**3)
    if isinstance(socket, int):
        http_server.add_sockets(tornado.netutil.bind_sockets(socket))
    else:
        http_server.add_socket(tornado.netutil.bind_unix_socket(socket))

    signal.signal(signal.SIGINT, sigint_handler)

    tornado.ioloop.PeriodicCallback(periodicCleanup, 60 * 60 * 1000).start() # run periodicCleanup once an hour
    # start it up
    tornado.ioloop.IOLoop.instance().start()

    if qm is not None:
        qm.end()


def sigint_handler(signum, frame):
    tornado.ioloop.IOLoop.instance().stop()

if __name__ == "__main__":
    main()
