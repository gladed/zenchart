from urllib2 import Request, urlopen, HTTPError
import json, datetime, logging

zenhubUrl = 'https://api.zenhub.io/p1'

class Zenhub:
    def __init__(self, repo):
        """Construct a zenhub object for a given repo"""
        self.repo = repo

    def get(self, url):
        if zenhubUrl not in url:
            url = '%s/repositories/%s%s' % (zenhubUrl, self.repo.data['id'], url)
        logging.info('zenhub GET ' + url)
        request = Request(url)
        request.add_header('X-Authentication-Token', self.repo.auth.zenhubToken)
        return json.load(urlopen(request))
#        except HTTPError, err:
#            logging.info('Uh oh: %s', err)

    def issue(self, number):
        """Load an issue with events from zenhub"""
        issue = self.get('/issues/%s' % number) 
        issue['events'] = self.get('/issues/%s/events' % number)
        return issue

    def syncIssues(self):
        for issue in self.repo.issues():
            if not hasattr(issue, 'zenhub') or not issue.zenhubUpdate:
                now = datetime.datetime.now()
                issue.zenhub = self.issue(issue.number)
                issue.zenhubUpdate = now
                issue.upsert()

def syncIssues(repoKey):
    try:
        Zenhub(repoKey.get()).syncIssues()
    except HTTPError as e:
        if e.code == 403:
            logging.info('Zenhub returned 403, trying again after a while...')
            deferred.defer(syncIssues, repoKey, _countdown=20)
        else:
            logging.exception('Failed to sync Zenhub issues')
    except:
        logging.exception('Failed to sync Zenhub issues')
