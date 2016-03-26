#!/usr/bin/python
import os
import webapp2, jinja2, logging
import urllib, cgi, json
from google.appengine.ext import ndb
from google.appengine.api import taskqueue
import github
from model import Auth, Repo
from google.appengine.ext import deferred

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__) + '/html'),
    extensions=['jinja2.ext.autoescape'],
    autoescape=True)

class MainPage(webapp2.RequestHandler):
    def get(self):
        repos = Repo.queryAll().order(Repo.name).fetch(50)
        self.response.write(JINJA_ENVIRONMENT.get_template('index.html').render({'repos': repos}))

class AddRepo(webapp2.RequestHandler):
    def post(self):
        name = self.request.get('repoName')
        repo = Repo()
        repo.name = name
        repo.auth = Auth()
        repo.auth.zenhubToken = self.request.get('zenhubToken')
        repo.auth.githubToken = self.request.get('githubToken')
        repo.auth.githubUser = self.request.get('githubUser')
	repo.put()
        deferred.defer(github.getAllIssues, repo)
        self.redirect(repo.url())

class RepoPage(webapp2.RequestHandler):
    def get(self, id):
        repo = Repo.get(id)
        issues = sorted(repo.issues(), key=lambda x: x.number, reverse=True)
        if not repo:
            self.response.set_status(404)
        else:
            self.response.write(JINJA_ENVIRONMENT.get_template('repo.html').render({'repo': repo, 'issues': issues}))

class IssuePage(webapp2.RequestHandler):
    def get(self, id, number):
        repo = Repo.get(id)
        if not repo:
            self.response.set_status(404)
        else:
            issue = repo.issue(number)
            if not issue:
                self.response.set_status(404)
            else:
                full = { 'github': issue.github, 'zenhub': issue.zenhub }
                self.response.headers['Content-Type'] = 'application/json'
                self.response.out.write(json.dumps(full, indent=2))

class RepoSyncPage(webapp2.RequestHandler):
    def post(self, id):
        repo = Repo.get(id)
        if not repo:
            self.response.set_status(404)
        else:
            # TODO: don't resync more often than X?
            deferred.defer(github.syncIssues, repo)
            #deferred.defer(github.getAllIssues, repo)
            #taskqueue.add(url=repo.url() + '/task/sync')
            self.redirect(repo.url())

class RepoDeletePage(webapp2.RequestHandler):
    def post(self, id):
        repo = Repo.get(id)
        if repo:
            repo.key.delete()
            self.redirect('/') 
        else:
            self.response.set_status(404)

DEBUG = True

class RepoTaskSync(webapp2.RequestHandler):
    def post(self, id):
        if not DEBUG and 'X-AppEngine-QueueName' not in self.request.headers:
            self.response.set_status(400)
        else:
            repo = Repo.get(id)
            if not repo:
                self.response.set_status(404)
            else:
                logging.info("Sync Beginning")
                github.syncIssues(repo)
                self.response.write("OK")

app = webapp2.WSGIApplication([
    ('/', MainPage),
    ('/addRepo', AddRepo),
    webapp2.Route(r'/repo/<id:\d+>', RepoPage),
    webapp2.Route(r'/repo/<id:\d+>/delete', RepoDeletePage),
    webapp2.Route(r'/repo/<id:\d+>/sync', RepoSyncPage),
    webapp2.Route(r'/repo/<id:\d+>/task/sync', RepoTaskSync),
    webapp2.Route(r'/repo/<id:\d+>/issue/<number:\d+>', IssuePage),
],debug=True)
