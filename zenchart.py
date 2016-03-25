#!/usr/bin/python
import os
import webapp2, jinja2, logging
import urllib, cgi
from google.appengine.ext import ndb

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'],
    autoescape=True)

# TODO: In the future this should come from the current user id
repoKey = ndb.Key('Repo', 'allrepos')

class Auth(ndb.Model):
    zenhubToken = ndb.StringProperty()
    githubUser = ndb.StringProperty()
    githubToken = ndb.StringProperty()

class Issue(ndb.Model):
    number = ndb.IntegerProperty(indexed=True)
    repoName = ndb.StringProperty(indexed=True)
    data = ndb.JsonProperty()
    updated = ndb.DateTimeProperty(auto_now=True)

class Repo(ndb.Model):
    auth = ndb.StructuredProperty(Auth)
    name = ndb.StringProperty(indexed=True)
    data = ndb.JsonProperty()
    updated = ndb.DateTimeProperty(auto_now=True)
    def url(self):
        return '/repo/%s' % urllib.quote(str(self.key.id()), safe='')
 
class MainPage(webapp2.RequestHandler):
    def get(self):
        repos = Repo.query(ancestor = repoKey).order(Repo.name).fetch(50)
        self.response.write(JINJA_ENVIRONMENT.get_template('index.html').render({'repos': repos}))

class AddRepo(webapp2.RequestHandler):
    def post(self):
        name = self.request.get('repoName')
        repo = Repo(parent=repoKey)
        repo.name = name
        repo.auth = Auth()
        repo.auth.zenhubToken = self.request.get('zenhubToken')
        repo.auth.githubToken = self.request.get('githubToken')
        repo.auth.githubUser = self.request.get('githubUser')
	repo.put()
        self.redirect(repo.url())

class RepoPage(webapp2.RequestHandler):
    def get(self, id):
        repo = Repo.get_by_id(int(id), parent=repoKey)
        if not repo:
            self.response.set_status(404)
        else:
            self.response.write(JINJA_ENVIRONMENT.get_template('repo.html').render({'repo': repo}))

class DeleteRepoPage(webapp2.RequestHandler):
    def post(self, id):
        repo = Repo.get_by_id(int(id), parent=repoKey)
        if repo:
            repo.key.delete()
            self.redirect('/') 

app = webapp2.WSGIApplication([
    ('/', MainPage),
    ('/addRepo', AddRepo),
    webapp2.Route(r'/repo/<id:\d+>', RepoPage),
    webapp2.Route(r'/repo/<id:\d+>/delete', DeleteRepoPage),
],debug=True)
