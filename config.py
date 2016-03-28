import yaml, os, logging

# Load config
config = yaml.load(open('config.yaml','r'))

# Enforce some defaults
config['webapp2_extras.auth'] = { 'session_backend': 'memcache' }

