#!/usr/bin/python
import os
import webapp2, jinja2, logging
import urllib, cgi, json
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
        user = self.user()

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
        repo.put()
        logging.info("Putting repo %s" % repo)
        # TODO: defer get all issues for this repo
        self.redirect(repo.url())

class RepoPage(BaseHandler):
    def get(self, id):
        user = self.user()
        repo = Repo.get(user, id)
        if self.request.get('s'):
            logging.info("Deferring github repo issue sync")
            deferred.defer(github.syncIssues, user, repo.key)
            self.redirect(repo.url())
        elif self.request.get('z'):
            logging.info("Deferring zenhub repo issue sync")
            deferred.defer(zenhub.syncIssues, repo.key)
            self.redirect(repo.url())
        elif self.request.get('f'):
            deferred.defer(github.getAllIssues, user, repo.key)
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

class RepoSyncPage(webapp2.RequestHandler):
    def post(self, id):
        repo = Repo.get(id)
        if not repo:
            self.response.set_status(404)
        else:
            deferred.defer(github.syncIssues, repo)
            #deferred.defer(github.getAllIssues, repo)
            #taskqueue.add(url=repo.url() + '/task/sync')
            self.redirect(repo.url())

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
                #github.syncIssues(repo)
                #deferred.defer(github.getAllIssues, repo)
                deferred.defer(github.getZenhubIssues, repo.key)
                self.response.write("OK")

class LoginPage(BaseHandler):
    def get(self):
        self.session['return'] = self.request.get('r')
        # TODO: If user is missing we should allow redirection back to the current route 
        url = github.authUrl(self.session)
        logging.info('Redirecting to %s to get user info' % url)
        self.redirect(url)

class LogoutPage(BaseHandler):
    def get(self):
        self.session.clear()
        self.redirect('/')

class GithubAuthPage(BaseHandler):
    def get(self):
        # TODO: Verify the 'state'
        code = self.request.GET['code']
        state = self.request.GET['state']
        github.getAccessToken(self.session, code, state)
        if 'return' in self.session:
            returnTo = self.session['return']
            del session['return']
        else:
            returnTo = '/'
        self.redirect(returnTo)

app = webapp2.WSGIApplication([
    ('/', MainPage),
    ('/repo/add', RepoAddPage),
    ('/addRepo', AddRepo),
    ('/login', LoginPage),
    ('/logout', LogoutPage),
    webapp2.Route(r'/repo/<id:\d+>', RepoPage),
    webapp2.Route(r'/repo/<id:\d+>/delete', RepoDeletePage),
    webapp2.Route(r'/repo/<id:\d+>/sync', RepoSyncPage),
    webapp2.Route(r'/repo/<id:\d+>/task/sync', RepoTaskSync),
    webapp2.Route(r'/repo/<id:\d+>/issue/<number:\d+>', IssuePage),
    ('/auth/github', GithubAuthPage),
],debug=True,config=config)
