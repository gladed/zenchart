import webapp2, sys, urllib, urlparse, random
import base64, json, logging, datetime, time
from urllib2 import Request, urlopen, HTTPError
from google.appengine.ext import deferred
from google.appengine.ext import vendor
vendor.add('lib') # uritemplate is vendored
import uritemplate
from model import Issue, Repo
import zenhub

githubUrl = 'https://api.github.com'

class Github:
    def __init__(self, me):
        self.me = me

    def get(self, url):
        logging.info('github GET ' + url)
        request = Request(url)
        # Add credentials as we have them
        if 'paToken' in self.me:
            #logging.info("Adding personal access token from session")
            encoded = base64.b64encode(':%s' % self.me['paToken'])
            request.add_header('Authorization', 'Basic ' + encoded)
        elif 'aToken' in self.me:
            request.add_header('Authorization', 'token ' + self.me['aToken'])
        return json.load(urlopen(request))

    def getAll(self, url):
        """Fetches pages of items"""
        pageSize = 50
        pageNumber = 0
        items = []
        more = True
        if '?' not in url: 
           url += '?'
        else:
           url += '&'
        while more:
            page = self.get(url + 'per_page=%d&page=%d' % (pageSize, pageNumber))
            items.extend(page)
            pageNumber += 1
            more = len(page) == pageSize
        return items

    def repos(self):
        repos = self.get(self.me['repos_url'])
        subs = self.get(self.me['subscriptions_url'])
        repoNames = map(lambda r: r['full_name'], repos)
        for sub in subs:
            if sub['full_name'] not in repoNames:
                repos.append(sub)
        return repos

    def repo(self, name):
        return self.get(githubUrl + '/repos/' + name)

    def user(self):
        """Get user info from github and store it in the session"""
        return self.get('%s/user' % githubUrl)

    def issue(self, repo, number, oldData=None):
        """Return github issue and event data"""
        url = uritemplate.expand(repo.data['issues_url'], { 'number': number })
        issue = self.get(url)
        # TODO: only get events up to the most recent in oldData?
        issue['events'] = self.getAll(issue['events_url'])
        logging.info('Found %d events for #%s' % (len(issue['events']), number))
        return issue

    def storeIssue(self, repo, issueData, updateTime = None):
        """Update database with issue data"""
        number = issueData['number']
        issue = repo.issue(number)
        if 'modified_at' in issueData and not updateTime:
            updateTime = issueData['modified_at']
        if not issue:
            issue = Issue(repo = repo.key, number = number)
        issue.github = self.issue(repo, number, issue.github)
        issue.githubUpdate = updateTime
        issue.zenhubUpdate = None  # mark for Zenhub update
        logging.info("Upserting issue %s" % issue.number)
        issue.upsert()

    def issues(self, repo):
        """Fetch all issues from github"""

    def syncIssues(self, repo, deep=False):

        issues = repo.issues()
        if issues:
            issueTime = max(map(lambda x: x.githubUpdate, issues))
        else:
            issueTime = None
    
        if deep:
            logging.info("Getting all issues")
            url = uritemplate.expand(repo.data['issues_url'], { }) + '?state=all'
            for issue in self.getAll(url):
                self.storeIssue(repo, issue)
        else:
            logging.info("Getting updated issues since %s" % issueTime)
            numbers, updateTime = self.newIssueNumbers(repo, issueTime)
            for number in numbers:
                repo.key.get() # Make sure repo is there or throw
                self.storeIssue(repo, self.issue(repo, number), updateTime)

        # When github sync is successful, launch a follow-up zenhub sync
        zenhub.syncIssues(repo.key)
    
    def newIssueNumbers(self, repo, until):
        """Return issues that changed after issueTime, along with most recent update time"""
        numbers = set()
        latestTime = None
        for page in range(0, 10):
            url = repo.data['events_url'] + '?page=%d' % page
            for event in self.get(url):
                latestTime = max(latestTime, event['created_at'])
                if event['created_at'] <= until:
                    # We are done, fetch no more
                    return numbers, latestTime
                elif 'issue' in event['payload']:
                    numbers.add(event['payload']['issue']['number'])
        return list(numbers), latestTime

def syncIssues(user, repoKey, deep=False):
    try:
        repo = repoKey.get()
        repo.syncing = True
        repo.put()
        Github(user).syncIssues(repo, deep)
        # Do not turn off sync bit, zenhub will do that.
    except:
        logging.exception('Failed to sync Github issues')
        try:
            repo = repoKey.get()
            repo.syncing = False
            repo.put()
        except:
            pass
