#!/usr/bin/env python3

import json
import tornado.web
import db
import random
import datetime
from operator import itemgetter
import pprint

import handler
import settings
import util

class SeatingAlg():
    name = None
    def seat(self, players, round = 1):
        return players

class Random(SeatingAlg):
    name = "Random"
    def seat(self, players, round = 1):
        players = players[:]
        random.shuffle(players)
        return players

class Snake(SeatingAlg):
    name = "Snake"
    def seat(self, players, round = 1):
        rowlen = int(len(players) / 4)
        numplayers = rowlen * 4
        players = [players[i:i + rowlen] for i in range(0, numplayers, rowlen)]
        for i, row in enumerate(players):
            if i % 2 == 1:
                row.reverse()
        return list(sum(zip(*players), ()))

class StraightAcross(SeatingAlg):
    name = "Straight Across"
    def seat(self, players, round = 1):
        if len(players) <= 4:
            return players
        rowlen = int(len(players) / 4)
        numplayers = rowlen * 4
        players = [players[i:i + rowlen] for i in range(0, numplayers, rowlen)]
        return list(sum(zip(*players), ()))

class Wheel(SeatingAlg):
    name = "Wheel"
    def seat(self, players, round = 1):
        if len(players) <= 4:
            return players
        wheellen = int(len(players) / 4)
        numplayers = wheellen * 4
        players = [players[i:i + wheellen] for i in range(0, numplayers, wheellen)]
        offset = (round - 1) % wheellen
        for i in range(len(players)):
            players[i] = players[i][offset * i:] + players[i][0:offset * i]
        return list(sum(zip(*players), ()))

ALGORITHMS = [
    Random(),
    Snake(),
    StraightAcross(),
    Wheel()
]

ORDERINGS = [
    ("Number", "ORDER BY Players.Number ASC"),
    ("Score", "ORDER BY TotalScore DESC, Penalty DESC"),
    ("Rank", "ORDER BY LastRank ASC, TotalScore DESC, Penalty DESC"),
    ("Wheel", "ORDER BY Players.Wheel ASC, Players.Number ASC, TotalScore DESC, Penalty DESC")
]

class AlgorithmsHandler(handler.BaseHandler):
    def get(self):
        return self.write(json.dumps(
            [
                {
                    'Id': num,
                    'Name': alg.name
                }
                for num, alg in enumerate(ALGORITHMS)
            ]
        ))

class OrderingsHandler(handler.BaseHandler):
    def get(self):
        return self.write(json.dumps(
            [
                {
                    'Id': num,
                    'Name': ordering[0]
                }
                for num, ordering in enumerate(ORDERINGS)
            ]
        ))

def countriesHeuristic(oldheuristic = None, factor = 1):
    return lambda p1, p2: \
            (factor if "Country" in p1 and "Country" in p2 and p1["Country"] == p2["Country"] else 0) + (oldheuristic(p1, p2) if oldheuristic is not None else 0)

def duplicatesHeuristic(oldheuristic = None, factor = 1, players = [], round = None):
    playergames = \
        (lambda games:
            lambda p1, p2:
                games[(p1, p2)] if (p1, p2)  in games else (
                        games[(p2, p1)] if (p2, p1) in games else 0)
        )(playerGames(players, round))
    return (lambda playergames:
                lambda p1, p2:
                     (playergames(p1["Id"], p2["Id"]) * factor + (oldheuristic(p1, p2) if oldheuristic is not None else 0))
            )(playergames)

def duplicateCountHeuristic(oldheuristic = None, factor = 1, players = [], round = None):
    playergames = \
        (lambda games:
            lambda p1, p2:
                1 if (p1, p2)  in games else (
                        1 if (p2, p1) in games else 0)
        )(playerGames(players, round))
    return (lambda playergames:
                lambda p1, p2:
                     (playergames(p1["Id"], p2["Id"]) * factor + (oldheuristic(p1, p2) if oldheuristic is not None else 0))
            )(playergames)

def noHeuristic():
    return lambda p1, p2: 0

def getSeating(tournamentID, roundId = None):
    with db.getCur() as cur:
        query = """
                SELECT Rounds.Id,
                 Rounds.Number,
                 Rounds.Name,
                 Rounds.Winds,
                 Seating.CutName,
                 Seating.TableNum,
                 Seating.Wind,
                 Players.Id,
                 Players.Name,
                 Countries.Code,
                 Countries.Flag_Image,
                 Players.Country,
                 COALESCE(Players.Association, ''),
                 Scores.Id,
                 COALESCE(Scores.Rank, 0),
                 COALESCE(Scores.RawScore, 0),
                 COALESCE(Scores.Score, 0),
                 COALESCE(PenaltyPoints.sum, 0)
                 FROM Rounds
                 LEFT OUTER JOIN Seating
                   ON Rounds.Id = Seating.Round
                 LEFT OUTER JOIN Players
                   ON Players.Id = Seating.Player
                 LEFT OUTER JOIN Scores
                   ON Rounds.Id = Scores.Round AND Players.Id = Scores.PlayerId
                      AND Seating.TableNum = Scores.GameID
                 LEFT OUTER JOIN
                   (SELECT Players.Id, Round, GameId,
                           COALESCE(SUM(Penalty), 0) as sum
                      FROM Players
                        LEFT OUTER JOIN Scores ON Players.Id = Scores.PlayerId
                        LEFT OUTER JOIN Penalties ON Scores.Id = Penalties.ScoreId
                        GROUP BY Players.Id, Round, GameId) AS PenaltyPoints
                   ON Players.Id = PenaltyPoints.Id AND
                      Scores.Round = PenaltyPoints.Round AND
                      Scores.GameId = PenaltyPoints.GameId
                 LEFT OUTER JOIN Countries
                   ON Countries.Id = Players.Country
                 WHERE Rounds.Tournament = ?
                 ORDER BY Rounds.Number ASC, Seating.TableNum ASC, 
                   Seating.Wind ASC
            """
        bindings = (tournamentID,)
        if roundId is not None:
            query += " AND Rounds.Id = ?"
            bindings = (tournamentID, roundId)
        cur.execute(query, bindings)
        rounds = {}
        for row in cur.fetchall():
            (roundID, roundNum, roundname, winds, cutName, table, wind,
             playerid, name, country, flag, countryid, association, scoreid,
             rank, rawscore, score, penalty)  = row
            if roundID is not None:
                if not roundID in rounds:
                    rounds[roundID] = {
                        'winds':winds,
                        'name':roundname,
                        'number':roundNum,
                        'tables':{},
                        'has_scores': False
                    }
                if table is not None:
                    if not table in rounds[roundID]['tables']:
                        rounds[roundID]['tables'][table] = {
                            'unusedPoints': {'scoreid': '', 'rawscore': 0},
                            'cutName': cutName,
                        }
                    if wind is not None and name is not None:
                        rounds[roundID]['has_scores'] |= rawscore > 0
                    rounds[roundID]['tables'][table][wind] = {
                        "id": playerid,
                        "name" :name,
                        "country": country,
                        "countryid": countryid,
                        "flag": flag,
                        "association": association,
                        "scoreid": scoreid,
                        "rank": rank,
                        "rawscore": rawscore,
                        "score": round(score, 1) if isinstance(score, float) 
                        else score,
                        "penalty": penalty
                    }
        cur.execute("""SELECT Scores.Id, Rounds.Id, GameId, RawScore
                         FROM Scores
                         LEFT OUTER JOIN Rounds
                           ON Rounds.Id = Scores.Round
                           WHERE Scores.PlayerId = ? AND Rounds.Tournament = ?
                           """,
                    (db.getUnusedPointsPlayerID(), tournamentID))
        for Id, Round, GameId, RawScore in cur.fetchall():
            if Round in rounds:
                rounds[Round]['tables'][GameId]['unusedPoints'] = {
                    'scoreid': Id, 'rawscore': RawScore}

        rounds = [
                {
                    'round':      roundID,
                    'number':     rounddict['number'],
                    'name':       rounddict['name'],
                    'winds':      rounddict['winds'],
                    'has_scores': rounddict['has_scores'],
                    'tables':
                        [
                            {
                                'table':table,
                                'cutName': players['cutName'],
                                'players':
                                    [
                                        {
                                            'player': playerrec,
                                            'wind':util.winds[wind]
                                        }
                                        for wind, playerrec in players.items()
                                        if isinstance(wind, int)
                                    ],
                                'unusedPoints': players['unusedPoints']
                            }
                            for table, players in rounddict['tables'].items()
                        ]
                }
                for roundID, rounddict in rounds.items()
            ]
        for a_round in rounds:
            players = []
            for table in a_round['tables']:
                table['total'] = (table['unusedPoints']['rawscore'] +
                                  sum([player['player']['rawscore']
                                       for player in table['players']]))
                players += [{
                    "Id": player['player']['id'],
                    "Country": player['player']['countryid']
                } for player in table['players']]
            a_round['diversityplayers'], a_round['diversity'] = tablesScore(
                players, countriesHeuristic())
            a_round['duplicateplayers'], a_round['duplicates'] = tablesScore(
                players, duplicateCountHeuristic(players = players,
                                                 round = a_round['round']))
        return rounds

class SeatingCsvHandler(handler.BaseHandler):
    @handler.tournament_handler
    def get(self):
        round = int(self.get_argument("round", 1))
        rounds = getSeating(self.tournamentid, round)
        self.set_header("Content-Type", "text/csv")
        for r in rounds:
            if r["round"] == round:
                return self.render("tables.csv", round = r)
        return self.render("tables.csv", round = {
            'winds':False,
            'tables':[]
            })

class ShowSeatingHandler(handler.BaseHandler):
    @handler.tournament_handler
    def get(self):
        return self.render("tables.html", rounds=getSeating(self.tournamentid),
                           umas_4_player=settings.UMAS[4], winds=util.winds,
                           unusedPointsIncrement=settings.UNUSEDSCOREINCREMENT,
                           unusedPointsPlayerID=db.getUnusedPointsPlayerID())

class SwapSeatingHandler(handler.BaseHandler):
    @handler.tournament_handler_ajax
    @handler.is_owner_ajax
    def post(self):
        round = self.get_argument('round', None)
        left = self.get_argument('left', None)
        right = self.get_argument('right', None)
        ret = {"status":"error", "message":"Unknown error occurred"}
        if left == right:
            ret["message"] = "Can't swap a player with themself"
            return self.write(ret)
        with db.getCur() as cur:
            cur.execute(
                """SELECT Id, Player, TableNum, Wind
                    FROM Seating
                    WHERE Tournament = ?
                        AND Round = ?
                        AND (Player = ? OR Player = ?)""",
                (self.tournamentid, round, left, right)
            )
            rows = cur.fetchall()
            if len(rows) != 2:
                ret["message"] = "Can't find those two players in that round"
            elif rows[0][2] == rows[1][2]:  # Same table: swap winds
                cur.execute("UPDATE Seating SET Wind = ? WHERE Id = ?", (rows[0][3], rows[1][0]))
                cur.execute("UPDATE Seating SET Wind = ? WHERE Id = ?", (rows[1][3], rows[0][0]))
                ret["status"] = "success"
                ret["message"] = "Swapped seats"
            else:                           # Differnt table: swap player IDs
                cur.execute("UPDATE Seating SET Player = ? WHERE Id = ?", (rows[0][1], rows[1][0]))
                cur.execute("UPDATE Seating SET Player = ? WHERE Id = ?", (rows[1][1], rows[0][0]))
                ret["status"] = "success"
                ret["message"] = "Swapped players"
        return self.write(ret)

class SeatingHandler(handler.BaseHandler):
    @handler.tournament_handler_ajax
    def get(self):
        return self.write(json.dumps({'rounds':getSeating(self.tournamentid)}))
    @handler.tournament_handler_ajax
    @handler.is_owner_ajax
    def post(self):
        round = self.get_argument('round', None)
        if round is not None:
            ret = {"status":"error", "message":"Unknown error occurred"}
            with db.getCur() as cur:
                # Get round settings
                cur.execute(
                        """SELECT
                            Id,
                            COALESCE(Ordering, 0),
                            COALESCE(Algorithm, 0),
                            Seed,
                            Cut,
                            SoftCut,
                            CombineLastCut,
                            CutSize,
                            CutCount,
                            Duplicates,
                            Diversity,
                            UsePools
                             FROM Rounds WHERE Id = ? AND Tournament = ?""",
                        (round, self.tournamentid)
                    )
                round, ordering, algorithm, seed, cut, softcut, combineLastCut, cutsize, cutcount, duplicates, diversity, usepools = cur.fetchone()
                cut = cut == 1
                softcut = softcut == 1
                duplicates = duplicates == 1
                diversity = diversity == 1
                usepools = usepools == 1

                if (cut or softcut) and not cutsize:
                    cutsize = settings.DEFAULTCUTSIZE

                # Fetch players to be seated
                query = """
                        SELECT
                        Players.Id,
                        Players.Country,
                        Pool,
                        COALESCE(SUM(Scores.Score), 0) AS NetScore,
                        LastScore.Rank AS LastRank,
                        COALESCE(PenaltyPoints.sum, 0) AS Penalty,
                        COALESCE(SUM(Scores.Score), 0) + COALESCE(PenaltyPoints.sum, 0) AS TotalScore
                        FROM Players
                           LEFT OUTER JOIN Scores ON
                             Players.Id = Scores.PlayerId AND Scores.Round < ?
                           LEFT OUTER JOIN Scores AS LastScore ON
                             Players.Id = LastScore.PlayerId AND
                             LastScore.Round = ? - 1 AND LastScore.Rank != 0
                           LEFT JOIN Compete ON Compete.Player = Players.Id
                           LEFT OUTER JOIN
                             (SELECT Players.Id,
                                     COALESCE(SUM(Penalty), 0) as sum
                                FROM Players
                                  LEFT OUTER JOIN Scores
                                    ON Players.Id = Scores.PlayerId AND
                                       Scores.Round < ?
                                  LEFT OUTER JOIN Penalties
                                    ON Scores.Id = Penalties.ScoreId
                                GROUP BY Players.Id) AS PenaltyPoints
                             ON Players.Id = PenaltyPoints.Id
                         WHERE Compete.Type = 0
                         AND Tournament = ?
                         GROUP BY Players.Id
                    """
                query += ORDERINGS[ordering][1]
                cur.execute(query, (round, round, round, self.tournamentid))
                players = []
                for i, row in enumerate(cur.fetchall()):
                    player, country, pool, score, lastrank, penalty, total = row
                    if ordering != 2 or lastrank or round == 1:
                        players += [{
                                        "Rank":i,
                                        "Id": player,
                                        "Country": country,
                                        "Pool": pool,
                                        "LastRank": lastrank
                                    }]
                pools = {"": players}

                # Fetch substitutes
                query = """
                        SELECT
                        Players.Id
                         FROM Players
                           LEFT JOIN Countries ON Players.Country = Countries.Id
                           LEFT JOIN Compete ON Compete.Player = Players.Id
                         WHERE Compete.Type = 2
                         AND Tournament = ?
                         GROUP BY Players.Id
                    """
                cur.execute(query, (self.tournamentid,))
                subs = []
                for i, row in enumerate(cur.fetchall()):
                    subs += [{
                                    "Rank":len(players) + i,
                                    "Id":row[0]
                                }]

                # Assume no cuts
                for player in pools[""]:
                    player['cutName'] = ''
                    
                # Organize players into pools if enabled
                if usepools:
                    playerpools = pools
                    pools = {}
                    for pool, players in playerpools.items():
                        for player in players:
                            playerpool = pool + (player["Pool"] or "")
                            if not playerpool in pools:
                                pools[playerpool] = []
                            pools[playerpool] += [player]

                # Add substitutes to make pool sizes divisible by 4
                for pool in pools.values():
                    subsNeeded = (4 - len(pool) % 4)
                    if subsNeeded != 4:
                        if len(subs) >= subsNeeded:
                            pool += subs[0:subsNeeded]
                            subs = subs[subsNeeded:]
                        else:
                            ret["status"] = "warn"
                            ret["message"] = "Not enough substitutes to seat all players"
                            pool = pool[0:int(len(pool) / 4) * 4]

                # Cut seats only the top players, softcut groups players by ordering
                if softcut or cut:
                    playerpools = pools
                    pools = {}
                    for pool, players in playerpools.items():
                        if len(players) <= cutsize:
                            continue
                        i = 0
                        while i < (cutsize if cut else len(players)):
                            playerpool = pool + format(i, '04')
                            if not playerpool in pools:
                                pools[playerpool] = []

                            if not cutcount or i // cutsize < cutcount:
                                nextI = min(len(players), i + cutsize)
                            else:
                                nextI = len(players)
                            if (len(players) - nextI < cutsize and # If the next chunk wouldn't reach the cutsize,
                                    not cut and                    #   and this is not a hard cut,
                                    combineLastCut):               #   and we're combining smaller chunks
                                pools[playerpool] += players[i:]
                            elif nextI >= len(players):            # If this is the last chunk
                                pools[playerpool] += players[i:]
                            else:
                                pools[playerpool] += players[i:nextI]
                            i = nextI

                if seed is not None and len(seed) > 0:
                    random.seed(seed)

                players = []
                pools = list(pools.items())
                pools.sort(key=itemgetter(0))
                for poolname, pool in pools:
                    pool = ALGORITHMS[algorithm].seat(pool, round)
                    poolplayers, status = fixTables(pool, cur, duplicates, diversity, round)
                    for player in poolplayers:
                        player['cutName'] = poolname
                    players += poolplayers

                random.seed()

                if len(players) > 0:
                    bindings = []
                    for i, player in enumerate(players):
                        bindings += [(self.tournamentid, round, player["Id"], int(i / 4) + 1, i % 4, player['cutName'])]
                    cur.execute("DELETE FROM Seating WHERE Tournament = ? AND Round = ?", (self.tournamentid, round))
                    playerquery = ""
                    cur.executemany("""
                        INSERT INTO
                            Seating (Tournament, Round, Player, TableNum,
                                     Wind, CutName)
                            VALUES  (?,          ?,     ?,      ?, ?, ?)""",
                        bindings
                    )
                    if ret["status"] != "warn":
                        ret["status"] = "success"
                        improvements = []
                        if diversity:
                            improvements += ["diversity"]
                        if duplicates:
                            improvements += ["duplicates"]
                        if len(improvements) > 0:
                            ret["message"] = status
                        else:
                            ret["message"] = "Players successfully seated"
                self.write(json.dumps(ret))

def fixTables(players, cur, duplicates, diversity, round):
    if not diversity and not duplicates:
        return (players, "")

    if diversity:
        heuristic = countriesHeuristic()
    else:
        heuristic = None

    if duplicates:
        heuristic = duplicatesHeuristic(heuristic, settings.DUPLICATEIMPORTANCE, players, round)

    swaps = 0
    maxswap = 0
    iterations = 0
    while iterations < 5:
        swapsmade, distance = improvePlayers(players, heuristic)
        swaps += swapsmade
        maxswap = max(maxswap, distance)
        iterations += 1
        if swapsmade == 0:
            break

    score = tablesScore(players, heuristic)[1]

    status = "{0} swaps made (max distance {1}) in {3} phases to score {2}".format(
                                    str(swaps),
                                    maxswap,
                                    score,
                                    iterations)
    return (players, status)

def improvePlayers(players, heuristic):
    for i, player in enumerate(players):
        player["Seat"] = i

    t = 0
    swaps = 0
    maxswap = 0

    violations = tablesScore(players, heuristic, "Seat")[0]

    while violations:
        seat1 = violations.pop()
        seat2 = bestSwap(players, heuristic, seat1)
        if seat2 is not None:
            if seat2 in violations:
                violations.remove(seat2)
            players[seat1], players[seat2] = players[seat2], players[seat1]
            distance = abs(players[seat1]["Rank"] - players[seat2]["Rank"])
            maxswap = max(maxswap, distance)
            swaps += 1
    return (swaps, maxswap)

def bestSwap(players, heuristic, player):
    toReplace = players[player]
    oldplayer = player

    t = int(player / 4) * 4
    player = player - t

    table = players[t:t+4]

    replacements = players[0:t] + players[t + 4:]
    replacements.sort(key=lambda replacement:abs(replacement["Rank"] - toReplace["Rank"]))

    candidates = [(0, None)]

    for replacement in replacements:
        distance = abs(replacement["Rank"] - toReplace["Rank"])
        if distance > settings.MAXSWAPDISTANCE:
            break

        repPlayer = replacement["Seat"] % 4
        repTable = replacement["Seat"] - repPlayer
        repTable = players[repTable:repTable + 4]

        curTable = table[:]

        oldScore = tableScore(repTable, heuristic)[1] + tableScore(curTable, heuristic)[1]
        curTable[player], repTable[repPlayer] = repTable[repPlayer], curTable[player]
        newScore = tableScore(repTable, heuristic)[1] + tableScore(curTable, heuristic)[1]

        candidates += [((newScore - oldScore) + distance / settings.MAXSWAPDISTANCE, replacement["Seat"])]
    candidates.sort(key=itemgetter(0))

    return candidates[0][1]

def tablesScore(players, heuristic, viokey = "Id"):
    numplayers = len(players)

    violations = set()
    score = 0
    for i in range(0, numplayers, 4):
        table = players[i:i+4]
        violation, s = tableScore(table, heuristic, viokey)
        score += s
        violations = violations.union(violation)

    return (violations, score)

def tableScore(players, heuristic, viokey = "Id"):
    numplayers = len(players)

    violations = set()
    score = 0
    for i in range(numplayers):
        for j in range(i + 1, numplayers):
            violation = heuristic(players[i], players[j])
            score += violation
            if violation:
                violations.add(players[i][viokey])
                violations.add(players[j][viokey])

    return (violations, score)

def playerGames(players, round = None):
    numplayers = len(players)

    playergames = dict()

    query = """
        SELECT COUNT(*) FROM Scores
        INNER JOIN Scores AS Scores2 ON
        Scores.GameId = Scores2.GameId AND
        Scores.Round = Scores2.Round
        WHERE Scores.PlayerId = ? AND Scores2.PlayerId = ?
        """
    gbindings = []
    if round is not None:
        query += " AND Scores.Round < ?"
        gbindings += [round]
    with db.getCur() as c:
        for i in range(numplayers):
            for j in range(i + 1, numplayers):
                bindings = [players[i]['Id'], players[j]['Id']]
                games = c.execute(query, bindings + gbindings).fetchone()[0]
                if games != 0:
                    playergames[(players[i]['Id'], players[j]['Id'])] = games

    return playergames
