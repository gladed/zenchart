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

### Running locally

When authenticating locally, Github will redirect you to the registered
(public) URL. To complete the authentication process, replace the URL in your web client
with the local url, for example replace `http://whatever.appspot.com/auth/github?code=f0...ef&state=90..dd`
with `localhost:8080/auth/github?code=f0...ef&state=90..dd`.

