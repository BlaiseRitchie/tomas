#!/usr/bin/env python3

import datetime
import string
import random
import os
import json
import re
import urllib
import tornado.web
from passlib.hash import pbkdf2_sha256
import logging

import handler
import settings
import db
import util
import admin

log = logging.getLogger("WebServer")

def this_server(request):
    """Get the scheme and host to present to users for accessing this service.
    The request must be a Tornado request object for some URL on this site.
    """
    return settings.SERVERPREFIX or "{}://{}".format(
        request.protocol, request.host)

def format_invite(websitename, hostprefix, code):
    return """
<p>You've been invited to {websitename}\n<br />
Click <a href="{hostprefix}/verify/{code}">this link</a>
to accept the invite and register an account, or copy and paste the following
into your URL bar:<br />
{hostprefix}/verify/{code}</p>

<p>If you believe you received this email in error, it can be safely ignored.
It is likely a user simply entered your email by mistake.</p>""".format(
    websitename=websitename, hostprefix=hostprefix, code=code)

def expiration_date(start=None, duration=settings.LINKVALIDDAYS):
    if start is None:
        start = datetime.date.today()
    return start + datetime.timedelta(days=duration)

VerifyLinkIDLength = 32

class InviteHandler(handler.BaseHandler):
    @tornado.web.authenticated
    def get(self):
        if self.current_user is not None:
            self.render("invite.html")
        else:
            self.render("login.html", uri="invite")

    @tornado.web.authenticated
    def post(self):
        global VerifyLinkIDLength
        email = self.get_argument('email', None)
        if not db.valid['email'].match(email):
            self.render("invite.html",
                        message = "Please enter a valid email address.")
        else:
            with db.getCur() as cur:
                cur.execute("SELECT Email from Users where Email = ?", (email,))
                try:
                    existing = cur.fetchone()[0]
                    self.render("message.html",
                                message = "Account for {0} already exists.".format(
                                    email),
                                title="Duplicate Account")
                    return
                except:
                    pass
                code = util.randString(VerifyLinkIDLength)
                cur.execute("INSERT INTO VerifyLinks (Id, Email, Expires) "
                            "VALUES (?, LOWER(?), ?)",
                            (code, email, expiration_date().isoformat()))

            util.sendEmail(email,
                           "Your {0} Account".format(settings.WEBSITENAME),
                           format_invite(settings.WEBSITENAME,
                                         this_server(self.request), code))

            self.render("message.html",
                        message = "Invite sent. It will expire in {0} days."
                        .format(settings.LINKVALIDDAYS),
                        title = "Invite")

class SetupHandler(handler.BaseHandler):
    def get(self):
        with db.getCur() as cur:
            cur.execute("SELECT COUNT(*) FROM Users")
            if cur.fetchone()[0] != 0:
                self.redirect(settings.PROXYPREFIX)
            else:
                self.render("setup.html")
    def post(self):
        global VerifyLinkIDLength
        email = self.get_argument('email', None)
        if not db.valid['email'].match(email):
            self.render("setup.html",
                        message = "Please enter a valid email address.")
        else:
            with db.getCur() as cur:
                code = util.randString(VerifyLinkIDLength)
                cur.execute("INSERT INTO VerifyLinks (Id, Email, Expires) "
                            "VALUES (?, LOWER(?), ?)",
                            (code, email, expiration_date().isoformat()))

                if len(settings.EMAILPASSWORD) > 0:
                    util.sendEmail(email, "Your {0} Account".format(
                        settings.WEBSITENAME),
                                   format_invite(
                                       settings.WEBSITENAME,
                                       this_server(self.request), code))

                    self.render("message.html",
                                message = "Invite sent. It will expire in {0} days."
                                .format(settings.LINKVALIDDAYS),
                                title = "Invite")
                else:
                    self.redirect("{}/verify/{}".format(
                        settings.PROXYPREFIX.rstrip('/'), code))

class VerifyHandler(handler.BaseHandler):
	def get(self, q):
            with db.getCur() as cur:
                cur.execute(
                    "SELECT Email, Expires FROM VerifyLinks WHERE Id = ?",
                    (q,))
                try:
                    email, expires = cur.fetchone()
                except:
                    self.redirect(settings.PROXYPREFIX)
                    return

                if expires < datetime.date.today().isoformat():
                    cur.execute("DELETE FROM VerifyLinks WHERE Id = ?", (q,))
                    self.render("message.html",
                                message = "The invite expired {0}.  Please request another.".format(
                                    expires),
                                title="Expired Invite.")
                    return

                cur.execute("SELECT Email FROM Users WHERE Email = ?", (email,))
                try:
                    existing = cur.fetchone()[0]
                    cur.execute("DELETE FROM VerifyLinks WHERE Id = ?", (q,))

                    self.render("message.html",
                                message = "Account for {0} already exists.".format(
                                    email),
                                title="Duplicate Account")
                    return
                except:
                    pass
            self.render("verify.html", email = email, id = q)

	def post(self, q):
            email = self.get_argument('email', None)
            password = self.get_argument('password', None)
            vpassword = self.get_argument('vpassword', None)

            if email is None or password is None or vpassword is None or email == "" or password == "" or vpassword == "":
                self.render("verify.html", email = email, id = q,
                            message = "You must enter an email, a password, "
                            "and repeat your password exactly.")
                return
            if password != vpassword:
                self.render("verify.html", email = email, id = q,
                            message = "Your passwords didn't match")
                return

            with db.getCur() as cur:
                passhash = pbkdf2_sha256.encrypt(password)

                cur.execute("INSERT INTO Users (Email, Password) VALUES (LOWER(?), ?)", (email, passhash))
                log.info('Verified email {}'.format(email))
                cur.execute("SELECT COUNT(*) FROM Users")
                if cur.fetchone()[0] == 1:
                    cur.execute("INSERT INTO Admins SELECT Id FROM Users")
                    self.set_secure_cookie("admin", "1")
                    log.info('Granted admin privilege to user {}'.format(
                        cur.lastrowid))
                self.set_secure_cookie("user", str(cur.lastrowid))
                cur.execute("DELETE FROM VerifyLinks WHERE Id = ?", (q,))
                log.info('Removed verify link for {} (user {})'.format(
                    email, cur.lastrowid))

            self.redirect(settings.PROXYPREFIX)

class ResetPasswordHandler(handler.BaseHandler):
    def get(self):
        email = None
        if self.current_user:
            with db.getCur() as cur:
                cur.execute("SELECT Email FROM Users WHERE Id = ?", self.current_user)
                email = cur.fetchone()
                if email is not None:
                    email = email[0]
        self.render("forgotpassword.html", email = email)
    def post(self):
        global VerifyLinkIDLength
        with db.getCur() as cur:
            email = self.get_argument("email", None)
            cur.execute("SELECT Id FROM Users WHERE Email = ?", (email,))
            row = cur.fetchone()
            if row is not None:
                code = util.randString(VerifyLinkIDLength)
                cur.execute("INSERT INTO ResetLinks(Id, User, Expires) "
                            "VALUES (?, ?, ?)",
                            (code, row[0], expiration_date().isoformat()))

                util.sendEmail(
                    email, "Your {0} Account".format(settings.WEBSITENAME), """
<p>Here's the link to reset your {websitename} account password.<br />
Click <a href="{hostprefix}/reset/{code}">this link</a> to reset your password,
or copy and paste the following into your URL bar:<br />
{hostprefix}/reset/{code} </p>
""".format(websitename=settings.WEBSITENAME,
           hostprefix=this_server(self.request), code=code))
                self.render("message.html",
                            message = "Your password reset link has been sent")
            else:
                self.render("message.html",
                            message = "No account found associated with this email",
                            email = email)

class ResetPasswordLinkHandler(handler.BaseHandler):
    def get(self, q):
        with db.getCur() as cur:
            cur.execute(
                "SELECT Email FROM Users JOIN ResetLinks ON "
                "ResetLinks.User = Users.Id WHERE ResetLinks.Id = ? AND "
                "ResetLinks.Expires > datetime('now', 'localtime')", (q,))
            row = cur.fetchone()
            if row is None:
                self.render("message.html",
                            message = "Link is either invalid or has expired. "
                            "Please request a new one.")
            else:
                nexturi = self.get_argument("nexturi", None)
                nexttask = self.get_argument("nexttask", None)
                self.render("resetpassword.html", email = row[0], id = q,
                            nexturi=nexturi, nexttask=nexttask)

    def post(self, q):
        password = self.get_argument('password', None)
        vpassword = self.get_argument('vpassword', None)
        nexturi = self.get_argument('nexturi', None)
        nexttask = self.get_argument('nexttask', None)

        with db.getCur() as cur:
            cur.execute(
                "SELECT Users.Id, Email "
                "FROM Users JOIN ResetLinks ON ResetLinks.User = Users.Id "
                "WHERE ResetLinks.Id = ?",
                (q,))
            row = cur.fetchone()
            if row is None:
                self.render("message.html",
                            message = "Link is either invalid or has expired. "
                            "Please request a new one")
            else:
                id = row[0]
                email = row[1]
                if password is None or vpassword is None or password == "" or vpassword == "":
                    self.render("resetpassword.html", email = email, id = q,
                                nexturi=nexturi, nexttask=nexttask,
                                message = "You must enter a pasword and repeat "
                                "that password")
                    return
                if password != vpassword:
                    self.render("resetpassword.html", email = email, id = q,
                                nexturi=nexturi, nexttask=nexttask,
                                message = "Your passwords didn't match")
                    return
                passhash = pbkdf2_sha256.encrypt(password)

                cur.execute("UPDATE Users SET Password = ? WHERE Id = ?", (passhash, id))
                cur.execute("DELETE FROM ResetLinks WHERE Id = ?", (q,))
                self.render("message.html",
                    message = "The password for {} has been reset. {}".format(
                        email,
                        '<a href="{}">{}</a>'.format(nexturi, nexttask)
                        if nexturi and nexttask and
                        len(nexturi) * len(nexttask) > 0 else
                        'You may now <a href="{proxyprefix}login">Login</a>'.format(
                            proxyprefix=settings.PROXYPREFIX)))

class LoginHandler(handler.BaseHandler):
    def get(self):
        uri = self.get_argument("next", None)
        if self.current_user is not None:
            if uri is None:
                return self.render("message.html", message = "You're already logged in, would you like to <a href=\"{proxyprefix}logout\">Logout?</a>".format(proxyprefix=settings.PROXYPREFIX))
            else:
                return self.redirect(uri)

        self.render("login.html", uri = uri)

    def post(self):
        email = self.get_argument('email', None)
        password = self.get_argument('password', None)
        uri = self.get_argument('next', '..')

        if not email or not password or email == "" or password == "":
            self.render("login.html", uri = uri,
                        message = "Please enter an email and a password")
            return

        with db.getCur() as cur:
            cur.execute("SELECT Id, Password FROM Users WHERE Email = LOWER(?)", (email,))

            row = cur.fetchone()
            if row is not None:
                userID = row[0]
                passhash = row[1]

                if pbkdf2_sha256.verify(password, passhash):
                    self.set_secure_cookie("user", str(userID))
                    log.info("Successful login for {0} (ID = {1})".format(
                        email, userID))
                    cur.execute(
                        "SELECT EXISTS(SELECT * FROM Admins WHERE Id = ?)",
                        (userID,))
                    if cur.fetchone()[0] == 1:
                        log.info("and {0} is an admin user".format(
                            email))
                        self.set_secure_cookie("admin", "1")
                    cur.execute("SELECT Value FROM Preferences WHERE"
                                " UserId = ? AND Preference = 'stylesheet';",
                                (userID,))
                    res = cur.fetchone()
                    if res != None:
                        self.set_secure_cookie("stylesheet", res[0])

                    if userID != None:
                        self.redirect(uri)
                        return
        log.info("Invalid login attempt for {0}".format(email))
        self.render("login.html", message = "Incorrect email and password",
                    uri = uri)

class LogoutHandler(handler.BaseHandler):
    def get(self):
        uri = self.get_argument('next', '..')
        userID = util.stringify(self.get_secure_cookie("user"))
        log.info("Explicit logout for user ID {0}".format(userID))
        self.clear_cookie("user")
        self.clear_cookie("admin")
        self.redirect(uri)
