from google.appengine.ext import ndb
import urllib

def userKey(user): return ndb.Key('User', user['login'])

class Auth(ndb.Model):
    zenhubToken = ndb.StringProperty()

class Repo(ndb.Model):
    @classmethod
    def create(cls, user):
        repo = Repo(parent = userKey(user))
        return repo

    @classmethod
    def get(cls, user, id):
        return super(Repo, cls).get_by_id(int(id), parent=userKey(user))

    @classmethod
    def repos(cls, user):
        return Repo.query(ancestor = userKey(user)).fetch()
 
    auth = ndb.StructuredProperty(Auth)
    name = ndb.StringProperty(indexed=True)
    data = ndb.JsonProperty()
    updated = ndb.DateTimeProperty(auto_now=True)

    def url(self):
        return '/repo/%d' % self.key.id()

    def issues(self):
        return Issue.query(Issue.repo==self.key).fetch()

    def issue(self, number):
        results = Issue.query(Issue.repo==self.key, Issue.number==int(number)).fetch(1)
        if results:
            for result in results:
                return result

    def delete(self):
        """Remove this item and its children from the db"""
        for issue in self.issues():
            issue.key.delete()
        self.key.delete()

class Issue(ndb.Model):
    repo = ndb.KeyProperty(kind=Repo)
    number = ndb.IntegerProperty(indexed=True)
    github = ndb.JsonProperty()
    githubUpdate = ndb.StringProperty()
    zenhub = ndb.JsonProperty()
    zenhubUpdate = ndb.DateTimeProperty()
    updated = ndb.DateTimeProperty(auto_now=True)

    def upsert(self):
        """Store this object, with sensitivity to existing github/zenhub data"""                
        issues = Issue.query(Issue.repo==self.repo, Issue.number==self.number).fetch()
        if issues:
            # overwrite old data
            old = issues[0]
            self.key = old.key
            if self.github:
                old.github = self.github
                old.githubUpdate = self.githubUpdate
            if self.zenhub:
                old.zenhub = self.zenhub
                old.zenhubUpdate = self.zenhubUpdate
            old.put()
        else:
            self.put()

          
