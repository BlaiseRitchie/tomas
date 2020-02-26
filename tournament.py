#!/usr/bin/env python3

import json
import csv
import re
import io
import logging
import datetime
import sqlite3

import tornado.web
import handler
import db
import seating
import settings

log = logging.getLogger('WebServer')

class TournamentListHandler(handler.BaseHandler):
    def get(self):
        rows = []
        tournaments = []
        admintournaments = []
        tmt_fields = db.table_field_names('Tournaments')
        with db.getCur() as cur:
            cur.execute("SELECT COUNT(*) FROM Users")
            no_user = cur.fetchone()[0] == 0
            columns = ["Tournaments.{}".format(f) for f in tmt_fields] + [
                "Code", "Flag_Image"]
            colnames = [col.split(".")[-1] for col in columns] + [
                'PlayerCount']
            cur.execute("SELECT {columns}, COUNT(DISTINCT Compete.PLayer)"
                        " FROM Tournaments"
                        " JOIN Compete on Compete.Tournament = Tournaments.Id"
                        " JOIN Countries ON Tournaments.Country = Countries.Id"
                        " GROUP BY Tournaments.Id"
                        " ORDER BY End DESC".format(
                        columns=",".join(columns)))
            tournaments = [dict(zip(colnames, row)) for row in cur.fetchall()]
        return self.render("tournamentlist.html",
                tournaments=tournaments, no_user=no_user)

class EditTournamentHandler(handler.BaseHandler):
    tmt_fields = db.table_field_names('Tournaments')
    @tornado.web.authenticated
    def get(self, id=None):
        ctry_fields = db.table_field_names('Countries')
        tmt_fields = EditTournamentHandler.tmt_fields
        tmt_attr_fields = [f for f in tmt_fields if f != 'Id']
        with db.getCur() as cur:
            cur.execute("SELECT {} FROM Countries".format(
                ",".join(ctry_fields)))
            ctry_mapping = [(row[0], dict(zip(ctry_fields, row)))
                            for row in cur.fetchall()]
            countries = dict(ctry_mapping)
            def_country_id = ctry_mapping[0][1]["Id"]

            cur.execute("SELECT Id, Email FROM Users ORDER BY Email")
            users = dict(cur.fetchall())

            if id:
                cur.execute("SELECT {} FROM TOURNAMENTS WHERE Id = ?".format(
                    ",".join(tmt_fields)), (id,))
                results = cur.fetchall()
                if len(results) == 0:
                    return self.render(
                        "message.html",
                        message="Invalid tournament.",
                        next="Return to Tournament List",
                        next_url=settings.PROXYPREFIX)
                elif len(results) > 1:
                    return self.render(
                        "message.html",
                        message="ERROR multiple tournaments with ID {}."
                        "  Contact site administrator.".format(id),
                        next="Return to Tournament List",
                        next_url=settings.PROXYPREFIX)

                tournament = dict(zip(tmt_fields, results[0]))
                cur.execute("SELECT Name FROM Players"
                            " JOIN Compete on Compete.Player = Players.Id"
                            " WHERE Tournament = ?"
                            "  ORDER BY Name",
                            (id, ))
                tournament['Players'] = [row[0] for row in cur.fetchall()]
                cur.execute("SELECT COUNT(Scores.Id) FROM Scores"
                            "  JOIN Rounds ON Scores.Round = Rounds.Id"
                            "  WHERE Rounds.Tournament = ?",
                            (id,))
                tournament['ScoreCount'] = cur.fetchone()[0]
            else:
                tournament = dict(zip(tmt_fields, [''] * len(tmt_fields)))
                today = datetime.date.today()
                tomorrow = today + datetime.timedelta(days=1)
                tournament['Start'] = today.strftime(settings.DATEFORMAT)
                tournament['End'] = tomorrow.strftime(settings.DATEFORMAT)
                tournament['Country'] = def_country_id
                tournament['Owner'] = int(self.current_user)
                tournament['Players'] = []
                tournament['ScorePerPlayer'] = settings.DEFAULTSCOREPERPLAYER
                tournament['ScoreCount'] = 0
                sql = "INSERT INTO Tournaments ({}) VALUES ({})".format(
                    ', '.join(tmt_attr_fields),
                    ', '.join(['?'] * len(tmt_attr_fields)))
                try:
                    cur.execute(sql, [tournament[f] for f in tmt_attr_fields])
                    print('Created tournament', cur.lastrowid)
                    tournament['Id'] = cur.lastrowid
                except sqlite3.DatabaseError as e:
                    print('Error creating tournament ({}): {}'.format(sql, e))
                    return self.render(
                        'message.html',
                        message='Unable to create tournament: {}'.format(e))

            tournament['OwnerName'] = users[int(tournament['Owner'])]
            tournament['CountryCode'] = countries[tournament['Country']]['Code']
            tournament['CountryName'] = countries[tournament['Country']]['Name']
            tournament['Flag_Image'] = countries[tournament['Country']]['Flag_Image']

            if tournament['Owner'] == int(self.current_user) or self.get_is_admin():
                return self.render(
                    "edittournament.html",
                    tournament=tournament, users=users)
            else:
                return self.render(
                    "message.html",
                    message="ERROR only the tournament owner or administrators"
                    " may edit tournament attributes".format(id),
                    next="Return to Tournament List",
                    next_url=settings.PROXYPREFIX)

    @tornado.web.authenticated
    def post(self, id):
        tmt_fields = EditTournamentHandler.tmt_fields
        tmt_attr_fields = [f for f in tmt_fields if f != 'Id']
        state = {}
        for f in tmt_fields:
            state[f] = self.get_argument(f, None)
        if self.get_is_admin() or int(state['Owner']) == int(self.current_user):
            msg = 'Updated tournament {}'.format(state['Id'])
            if id == state['Id']:
                with db.getCur() as cur:
                    try:
                        for f in tmt_attr_fields:
                            sql = ("UPDATE Tournaments SET {} = ?"
                                   "  WHERE Id = ?").format(f)
                            cur.execute(sql, (state[f], id))
                        return self.write({'status': 'success', 'message': ''})
                    except sqlite3.DatabaseError as e:
                        print('Error updating tournament ({}): {}'.format(
                            sql, e))
                        return self.write({
                            'status': 'Error',
                            'message': 'Unable to update tournament {}: {}'
                            .format(id, e)})
            elif id and int(state['Id']) < 0:
                with db.getCur() as cur:
                    try:
                        sql = "DELETE FROM Tournaments WHERE Id = ?"
                        cur.execute(sql, (id,))
                        return self.write({
                            'status': 'load',
                            'message': 'Tournament Deleted',
                            'URL': settings.PROXYPREFIX})
                    except sqlite3.DatabaseError as e:
                        print('Error deleting tournament ({}): {}'.format(
                            sql, e))
                        return self.write({
                            'status': 'Error',
                            'message': 'Unable to update tournament {}: {}'
                            .format(id, e)})
            else:
                return self.write({'status': 'Error',
                                   'message': 'Inconsistent IDs {} and {}'.
                                   format(id, state['Id'])})
        else:
            self.write({'status': 'Error',
                        'message': 'You are not authorized to edit or create '
                        'that tournament.'})

class TournamentHandler(handler.BaseHandler):
    @handler.tournament_handler
    def get(self):
        tab = self.get_argument('tab', None)
        if tab:
            log.debug('Requested tab = {}'.format(tab))
        return self.render("tournament.html", tab=tab)

player_fields = ["id", "name", "number", "country", "countryid", "flag_image",
                 "association", "pool", "type", "wheel"]

def getPlayers(self, tournamentid):
    global player_fields
    with db.getCur() as cur:
        cur.execute(
            "SELECT Players.Id, Players.Name, Number, Countries.Code,"
            " Countries.Id, Flag_Image, Association, Pool, Type, Wheel"
            " FROM Players"
            " LEFT OUTER JOIN Countries"
            "   ON Countries.Id = Players.Country"
            " LEFT JOIN Compete ON Compete.Player = Players.Id"
            " INNER JOIN Tournaments"
            "   ON Tournaments.Id = Compete.Tournament"
            " WHERE Tournaments.Id = ?"
            " ORDER BY Players.Name asc",
            (tournamentid,))
        rows = [dict(zip(player_fields, row)) for row in cur.fetchall()]
        for row in rows:
            row['type'] = db.playertypes[int(row['type'] or 0)]
        editable = self.get_is_admin() or (self.current_user and
                                           self.current_user == str(self.owner))
    return {'players':rows, 'editable': editable}

class ShowPlayersHandler(handler.BaseHandler):
    @handler.tournament_handler
    def get(self):
        data = getPlayers(self, self.tournamentid)
        return self.render("players.html", editable = data['editable'],
                           players = data['players'])

class DeletePlayerHandler(handler.BaseHandler):
    @handler.tournament_handler_ajax
    @handler.is_owner_ajax
    def post(self):
        player = self.get_argument("player", None)
        if player is None:
            return self.write({'status':"error",
                               'message':"Please provide a player"})
        try:
            with db.getCur() as cur:
                if player == "all":
                    cur.execute("DELETE FROM Compete WHERE Tournament = ?",
                                (self.tournamentid,))
                else:
                    cur.execute("DELETE FROM Compete WHERE Player = ?"
                                " AND Tournament = ?",
                                (player, self.tournamentid))
                return self.write({'status':"success"})
        except:
            return self.write({'status':"error",
                 'message':"Couldn't delete player from tournament"})

class PlayersHandler(handler.BaseHandler):
    @handler.tournament_handler_ajax
    def get(self):
        return self.write(getPlayers(self, self.tournamentid))
    @handler.tournament_handler_ajax
    @handler.is_owner_ajax
    def post(self):
        global player_fields
        player = self.get_argument("player", None)
        if player is None or not (player.isdigit() or player == '-1'):
            return self.write({'status':"error", 'message':"Please provide a player"})
        info = self.get_argument("info", None)
        if info is None:
            return self.write({'status':"error", 'message':"Please provide an info object"})
        info = json.loads(info)
        try:
            fields = []
            with db.getCur() as cur:
                for colname, val in info.items():
                    col = colname.lower()
                    if not (col in player_fields and
                            (db.valid[col if col in db.valid else 'all'].match(
                                val))):
                        fields.append(col)
                    if player == '-1':
                        cur.execute("INSERT INTO Players (Name, Country, Tournament) VALUES"
                                    " ('\u202Fnewplayer',"
                                    "  (select Id from Countries limit 1), ?)", (self.tournamentid,))
                    else:
                        if colname == "Type" and val == str(
                                db.playertypecode['Substitute']):
                            cur.execute(
                                "UPDATE Players SET Country ="
                                "   (SELECT Id FROM Countries WHERE"
                                "      Name = 'Substitute' OR 'Code' = 'SUB'"
                                "             OR IOC_Code = 'SUB')"
                                " WHERE Id = ? AND Tournament = ?",
                                (player, self.tournamentid))
                        cur.execute("UPDATE Players SET {0} = ? WHERE Id = ? AND Tournament = ?"
                                    .format(colname),
                                    (val, player, self.tournamentid))
            if len(fields) > 0:
                return self.write(
                    {'status':"error",
                     'message':
                     "Invalid column(s) or value provided: {0}".format(
                         ", ".join(fields))})
            return self.write({'status':"success"})
        except:
            return self.write({'status':"error",
                 'message':"Invalid info provided"})

PlayerColumns = ["Name", "Number", "Country", "Association", "Pool", "Type", "Wheel"]
CountriesColumns = {"Country": "Code"}

class DownloadPlayersHandler(handler.BaseHandler):
    @handler.tournament_handler
    def get(self):
        global PlayerColumns, CountriesColumns
        colnames = [ 'Countries.{}'.format(CountriesColumns[c])
                     if c in CountriesColumns else 'Players.{}'.format(c)
                     for c in PlayerColumns ]
        with db.getCur() as cur:
            cur.execute(
                ("SELECT {colnames} FROM Players "
                 " LEFT OUTER JOIN Countries ON Countries.Id = Players.Country"
                 " LEFT JOIN Compete ON Compete.Player = Players.Id"
                 " WHERE Tournament = ?")
                .format(colnames=', '.join(colnames)), (self.tournamentid,))
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(PlayerColumns)
            for row in cur.fetchall():
                row = list(row)
                row[5] = db.playertypes[row[5]]
                writer.writerow(row)
            self.set_header("Content-Type", "text/csv")
            return self.write(output.getvalue())


class UploadPlayersHandler(handler.BaseHandler):
    @handler.tournament_handler_ajax
    @handler.is_owner_ajax
    def post(self):
        global PlayerColumns, CountriesColumns
        if 'file' not in self.request.files or len(self.request.files['file']) == 0:
            return self.write({'status':"error", 'message':"Please provide a players file"})
        players = self.request.files['file'][0]['body']
        colnames = [c.lower() for c in PlayerColumns]
        try:
            with db.getCur() as cur:
                reader = csv.reader(players.decode('utf-8').splitlines())
                good = 0
                bad = 0
                first = True
                unrecognized = []
                for row in reader:
                    hasheader = first and sum(
                        1 if v.lower() in colnames else 0 for v in row) >= len(row) - 1
                    first = False
                    if hasheader:
                        unrecognized = [v for v in row
                                        if v.lower() not in colnames]
                        colnames = [v.lower() for v in row]
                        colnames += [c.lower() for c in PlayerColumns
                                     if c.lower() not in colnames]
                        continue
                    if len(row) < 3:
                        bad += 1;
                        continue
                    filled = 0
                    for i in range(len(row)):
                        if row[i] == '':
                            row[i] = None
                        else:
                            filled += 1
                    if filled < 3:
                        bad += 1
                        continue
                    rowdict = dict(zip(
                        colnames, list(row) + [None] * len(colnames)))
                    if not (rowdict['name'] or
                            (rowdict['number'] and
                             not rowdict['number'].isdigit()) or
                            (rowdict['type'] and
                             not rowdict['type'] in db.playertypes)):
                        bad += 1
                        continue
                    rowdict['type'] = db.playertypecode[rowdict['type']] if (
                        rowdict['type'] in db.playertypecode) else 0
                    cur.execute(
                        "INSERT INTO Players(Name, Number, Country, "
                        "                    Association, Pool, Type, Wheel, Tournament)"
                        " VALUES(?, ?,"
                        "   (SELECT Id FROM Countries"
                        "      WHERE Name = ? OR Code = ? OR IOC_Code = ?),"
                        "   ?, ?, ?, ?, ?);",
                        (rowdict['name'], rowdict['number'], rowdict['country'],
                         rowdict['country'], rowdict['country'],
                         rowdict['association'], rowdict['pool'],
                         rowdict['type'], rowdict['wheel'], self.tournamentid))
                    good += 1
            message = ("{} player record(s) loaded, "
                       "{} player record(s) skipped").format(good,bad)
            if unrecognized:
                message += ", skipped column header(s): {}".format(
                    ', '.join(unrecognized))
            return self.write({'status':"success", 'message': message})
        except Exception as e:
            return self.write({'status':"error",
                    'message':"Invalid players file provided: " + str(e)})


class AddRoundHandler(handler.BaseHandler):
    @handler.tournament_handler_ajax
    @handler.is_owner_ajax
    def post(self):
        with db.getCur() as cur:
            print(self.tournamentid)
            cur.execute(
                "INSERT INTO Rounds(Number, Name, Tournament) "
                "VALUES((SELECT COUNT(*) + 1 FROM Rounds WHERE Tournament = ?),"
                "       'Round ' || (SELECT COUNT(*) + 1 FROM Rounds "
                "                    WHERE Tournament = ?),"
                "       ?)", (self.tournamentid,) * 3)
            return self.write({'status':"success"})

class DeleteRoundHandler(handler.BaseHandler):
    @handler.tournament_handler_ajax
    @handler.is_owner_ajax
    def post(self):
        round = self.get_argument("round", None)
        if round is None:
            return self.write({'status':"error", 'message':"Please provide a round"})
        with db.getCur() as cur:
            cur.execute("DELETE FROM Rounds WHERE Id = ? AND Tournament = ?", (round, self.tournamentid))
            return self.write({'status':"success"})

def getSettings(self, tournamentid):
    with db.getCur() as cur:
        cur.execute("""SELECT Id, Number, Name, COALESCE(Ordering, 0),
                        COALESCE(Algorithm, 0), Seed,
                        Cut, SoftCut, CutSize, CutMobility,
                        CombineLastCut, CutCount,
                        Duplicates, Diversity, UsePools, Winds, Games
                    FROM Rounds WHERE Tournament = ?
                    ORDER BY Number""", (tournamentid,))

        cols = ["id", "number", "name", "ordering", "algorithm", "seed",
                "cut", "softcut", "cutsize", "cutmobility",
                "combinelastcut", "cutcount",
                "duplicates", "diversity", "usepools", "winds", "games"]
        rounds = []

        for row in cur.fetchall():
            roundDict = dict(zip(cols, row))

            roundDict["orderingname"] = seating.ORDERINGS[roundDict["ordering"]][0]
            roundDict["algname"] = seating.ALGORITHMS[roundDict["algorithm"]].name
            roundDict["seed"] = roundDict["seed"] or ""

            rounds += [roundDict]

        cur.execute('SELECT COALESCE(ScorePerPlayer, {}) FROM Tournaments'
                    ' WHERE Id = ?'.format(settings.DEFAULTSCOREPERPLAYER),
                    (tournamentid,))
        result = cur.fetchone()
        if result is None:
            return None
        scorePerPlayer = result[0]
        return {'rounds':rounds,
                'scoreperplayer': scorePerPlayer,
                'unusedscoreincrement': settings.UNUSEDSCOREINCREMENT,
                'cutsize':settings.DEFAULTCUTSIZE}
    return None

class SettingsHandler(handler.BaseHandler):
    @handler.tournament_handler_ajax
    def get(self):
        return self.write(getSettings(self, self.tournamentid))
    @handler.tournament_handler_ajax
    @handler.is_owner_ajax
    def post(self):
        round = self.get_argument("round", None)
        if round is None:
            return self.write({'status':"error", 'message':"Please provide a round"})
        settings = self.get_argument("settings", None)
        if settings is None:
            return self.write({'status':"error", 'message':"Please provide a settings object"})
        settings = json.loads(settings)
        print(settings)
        with db.getCur() as cur:
            for colname, val in settings.items():
                cur.execute("UPDATE Rounds SET {0} = ? WHERE Id = ? AND Tournament = ?".format(colname),
                        (val, round, self.tournamentid)) # TODO: fix SQL injection
            return self.write({'status':"success"})


class ShowSettingsHandler(handler.BaseHandler):
    @handler.tournament_handler
    def get(self):
        roundsettings = getSettings(self, self.tournamentid)
        return self.render("roundsettings.html", rounds=roundsettings['rounds'], cutsize=roundsettings['cutsize'])

def getTourney(self, tournamentid):
    stage_fields = db.table_field_names('Stages')
    with db.getCur() as cur:
        cur.execute("""SELECT {} FROM Stages WHERE Tournament = ?
                       ORDER BY SortOrder, Id""".format(",".join(stage_fields)),
                    (tournamentid,))
        stages = dict((row[0], dict(zip(stage_fields, row)))
                      for row in cur.fetchall())
        roots = [id for id in stages if not stages[id]['PreviousStage']]
        if len(roots) > 1:
            raise Exception("Tournament {} has multiple initial stages".format(
                tournamentid))
        elif len(roots) == 0 and len(stages) > 0:
            raise Exception("Tournament {} has no initial stage but a cycle "
                            "of others".format(tournamentid))
        elif len(roots) == 0:
            stage = {'Tournament': tournamentid,
                     'Name': 'Round Robin',
                     'SortOrder': 0,
                     'PreviousStage': None,
                     'Ranks': None,
                     'Cumulative': 0,}
            cur.execute("""INSERT INTO Stages ({}) VALUES ({})""".format(
                ','.join(f for f in stage if stage[f] is not None),
                ','.join(repr(stage[f]) for f in stage
                         if stage[f] is not None)))
            stage['Id'] = cur.lastrowid
            stages = {cur.lastrowid: stage}
            roots = [cur.lastrowid]

        # List stages starting with root and then successor children, in order
        stagelist = [stages[roots[0]]]
        todo=stages.copy()
        del todo[roots[0]]
        while len(todo) > 0:
            children = [id for id in stages
                        if stages[id]['PreviousStage'] in roots]
            for child in sorted(children, key=lambda s: s['SortOrder']):
                stages[child]['previousName'] = stages[
                    stages[child]['PreviousStage']]['Name']
                stagelist.append(stages[child])
                del todo[child]
                roots.append(child)

        cols = ["id", "number", "name", "ordering", "algorithm", "seed",
                "cut", "softcut", "cutsize", "cutmobility", "combinelastcut",
                "duplicates", "diversity", "usepools", "winds", "games"]
        for stage in stagelist[:1]:
            cur.execute("""SELECT Id, Number, Name, COALESCE(Ordering, 0),
                             COALESCE(Algorithm, 0), Seed,
                             Cut, SoftCut, CutSize, CutMobility, CombineLastCut,
                             Duplicates, Diversity, UsePools, Winds, Games
                           FROM Rounds WHERE Tournament = ?
                           ORDER BY Number""", (tournamentid,))

            stage['rounds'] = []

            for row in cur.fetchall():
                roundDict = dict(zip(cols, row))
                roundDict["orderingname"] = seating.ORDERINGS[
                    roundDict["ordering"]][0]
                roundDict["algname"] = seating.ALGORITHMS[
                    roundDict["algorithm"]].name
                roundDict["seed"] = roundDict["seed"] or ""
                stage['rounds'] += [roundDict]

        cur.execute('SELECT COALESCE(ScorePerPlayer, {}) FROM Tournaments'
                    ' WHERE Id = ?'.format(settings.DEFAULTSCOREPERPLAYER),
                    (tournamentid,))
        result = cur.fetchone()
        if result is None:
            return None
        scorePerPlayer = result[0]
        return {'stages': stagelist, 'scoreperplayer': scorePerPlayer,
                'unusedscoreincrement': settings.UNUSEDSCOREINCREMENT,
                'cutsize':settings.DEFAULTCUTSIZE}

class TourneySettingsAjaxHandler(handler.BaseHandler):
    @handler.tournament_handler_ajax
    def get(self):
        return self.write(getTourney(self, self.tournamentid))

    @handler.tournament_handler_ajax
    @handler.is_owner_ajax
    def post(self):
        stage = self.get_argument("stage", None)
        if stage is None:
            return self.write({'status':"error",
                               'message':"Please provide a stage"})
        settings = self.get_argument("settings", None)
        if settings is None:
            return self.write({'status':"error",
                               'message':"Please provide a settings object"})
        settings = json.loads(settings)
        # print(settings)
        with db.getCur() as cur:
            for colname, val in settings.items():
                cur.execute("UPDATE Stages SET {} = ?"
                            " WHERE Id = ? AND Tournament = ?".format(colname),
                        (val, stage, self.tournamentid)) # TODO: fix SQL injection
            return self.write({'status':"success"})

class TourneySettingsHandler(handler.BaseHandler):
    @handler.tournament_handler
    def get(self):
        settings = getTourney(self, self.tournamentid)
        return self.render("tourney.html", **settings)

class CountriesHandler(handler.BaseHandler):
    def get(self):
        with db.getCur() as cur:
            cols = ["Id", "Name", "Code", "IOC_Code", "IOC_Name", "Flag_Image"]
            cur.execute("SELECT {cols} FROM Countries".format(cols=",".join(cols)))
            countries = [dict(zip(cols, row)) for row in cur.fetchall()]
            return self.write(json.dumps(countries))

class AssociationsHandler(handler.BaseHandler):
    @handler.tournament_handler
    def get(self):
        with db.getCur() as cur:
            cur.execute("SELECT DISTINCT Association FROM Players"
                        " LEFT JOIN Compete ON Compete.Player = Players.Id"
                        " WHERE Association IS NOT null"
                        "       AND length(Association) > 0"
                        "       AND Tournament = ?", (self.tournamentid,))
            return self.write(json.dumps([row[0] for row in cur.fetchall()]))
