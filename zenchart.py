#!/usr/bin/python
import os, random
import webapp2, jinja2, logging
import urllib, cgi, json, urllib2, urlparse
from google.appengine.ext import ndb
from google.appengine.api import taskqueue
import github
from model import Auth, Repo
from google.appengine.ext import deferred
from google.appengine.api import memcache
from webapp2_extras import sessions
import yaml
from config import config
from github import Github
import zenhub
import gc

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__) + '/html'),
    extensions=['jinja2.ext.autoescape'],
    autoescape=True)

class BaseHandler(webapp2.RequestHandler):
    def dispatch(self):
        self.session_store = sessions.get_store(request=self.request)
        try:
            webapp2.RequestHandler.dispatch(self)
        finally:
            self.session_store.save_sessions(self.response)
            gc.collect()

    def user(self):
        """Return the current user data or redirect to /login"""
        user = None
        if not 'user' in self.session and os.environ['APPLICATION_ID'].startswith('dev'):
            if self.request.get('paToken'):
                user = Github({'paToken': self.request.get('paToken')}).user()
                if user:
                    logging.info("Read user data %s" % json.dumps(user))
                    user['paToken'] = self.request.get('paToken')
                    self.session['user'] = user
                    return user
            # No user for now
            return None
        
        if 'user' in self.session:        
            return self.session['user']
         
        logging.info('No user detected; redirecting to /login')
        self.redirect('/login?%s' % urllib.urlencode({'r': self.request.path}), abort=True)
 
    @webapp2.cached_property
    def session(self):
        return self.session_store.get_session(backend='memcache')

class MainPage(BaseHandler):
    def get(self):
        user = None
        if 'user' in self.session:
            user = self.session['user']

        # List repositories that we know about
        if user: 
            repos = Repo.repos(user)
        else:
            repos = []
           
        self.response.write(JINJA_ENVIRONMENT.get_template('index.html').render({'user': user, 'repos': repos}))

class RepoAddPage(BaseHandler):
    def get(self):
        user = self.user() 
        repoNames = map(lambda r: r.name, Repo.repos(user))
        gitRepos = filter(lambda r: r['full_name'] not in repoNames, Github(user).repos())

        self.response.write(JINJA_ENVIRONMENT.get_template('repoAdd.html').render({
            'user': user,
            'repos': gitRepos}))

    def post(self): 
        user = self.user()       
        repo = Repo.create(user)
        repo.name = self.request.get('repo')
        repo.auth = Auth(zenhubToken = self.request.get('zenhubToken'))
        repo.data = Github(user).repo(repo.name)
        logging.info("Adding repo %s" % repo)
        repo.put()
        deferred.defer(github.syncIssues, user, repo.key)
        self.redirect(repo.url())

class RepoPage(BaseHandler):
    def get(self, id):
        user = self.user()
        repo = Repo.get(user, id)
        if self.request.get('s'):
            logging.info("Deferring github repo issue sync")
            deferred.defer(github.syncIssues, user, repo.key)
            self.redirect(repo.url())
        elif self.request.get('f'):
            deferred.defer(github.syncIssues, user, repo.key, True)
            self.redirect(repo.url())
        else:
            issues = sorted(repo.issues(), key=lambda x: x.number, reverse=True)
            if not repo:
                self.response.set_status(404)
            else:
                self.response.write(JINJA_ENVIRONMENT.get_template('repo.html').render({'user': user, 'repo': repo, 'issues': issues}))

class RepoDeletePage(BaseHandler):
    def post(self, id):
        user = self.user()
        repo = Repo.get(user, id)
        if repo:
            repo.delete()
            self.redirect('/') 
        else:
            self.response.set_status(404)


class IssuePage(BaseHandler):
    def get(self, id, number):
        user = self.user()
        repo = Repo.get(user, id)
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

class LoginPage(BaseHandler):
    def get(self):
        self.session['return'] = self.request.get('r')

        if self.request.get('paToken'):
            user = session.user()
            self.redirect('/')
        else:
            # Github login
            state = '%030x' % random.randrange(16**30)
            url = 'https://github.com/login/oauth/authorize?%s' % urllib.urlencode({
                'client_id': config['github']['id'],
                'scope': 'repo',
                'state': state})
            self.session['state'] = state
            logging.info('Redirecting to %s to get user info' % url)
            self.redirect(url)

class LogoutPage(BaseHandler):
    def get(self):
        self.session.clear()
        self.redirect('/')

class GithubAuthPage(BaseHandler):
    def get(self):
        code = self.request.GET['code']
        state = self.request.GET['state']
        if state != self.session['state']:
            self.response.set_status(403)
        else:
            request = urllib2.Request('https://github.com/login/oauth/access_token', urllib.urlencode({
                'client_id': config['github']['id'],
                'client_secret': config['github']['secret'],
                'code': code
            }))
            data = urlparse.parse_qs(urllib2.urlopen(request).read())
            logging.info('result is %s' % data)
            aToken = data['access_token'][0]           
            user = Github({'aToken': aToken}).user()
            user['aToken'] = aToken
            self.session['user'] = user
            if 'return' in self.session and self.session['return']:
                returnTo = self.session['return']
                logging.info("Login complete for user %s, returning to %s" % (json.dumps(user), returnTo))
                del self.session['return']
            else:
                returnTo = '/'
            self.redirect(returnTo)

app = webapp2.WSGIApplication([
    ('/', MainPage),
    ('/repo/add', RepoAddPage),
    ('/login', LoginPage),
    ('/logout', LogoutPage),
    webapp2.Route(r'/repo/<id:\d+>', RepoPage),
    webapp2.Route(r'/repo/<id:\d+>/delete', RepoDeletePage),
    webapp2.Route(r'/repo/<id:\d+>/issue/<number:\d+>', IssuePage),
    ('/auth/github', GithubAuthPage),
],debug=True,config=config)
