# ZenChart

Combines data from ZenHub.io and GitHub to make some interesting charts.

## Deployment

1. Create a new application in Google App Engine
2. Copy the application ID into `.gaeid`
3. Create a `config.yaml` as below.
3. From the root folder run `dev/update`

### `config.yaml`

```
# Github application credentials
github:
  id: <FROM GITHUB>
  secret: <FROM GITHUB>

# URL of the appspot host
host: <YOUR APP NAME>.appspot.com

# An app-specific secret session key
webapp2_extras.sessions:
  secret_key: <SOME LONG RANDOM THING>
```

