# SLP Token Validation Proxy Server

Electron-Cash-SLP can be run in daemon mode to serve token validation requests using the JSON RPC interface.  The following instructions explain how to set this service up using Ubuntu with nginx reverse proxy server. 

## Docker

The validation server can be run as a docker container.  See the `docker` folder for Dockerfiles for both mainnet and testnet.

For mainnet SLP validator use:
- `docker build -t ec-slp .`
- `docker run -d -p 5111:5111 --restart "always" ec-slp`
- Test: `curl --data-binary '{"jsonrpc": "2.0", "id":"testing", "method": "slpvalidate", "params": ["2504b5b6a6ec42b040a71abce1acd71592f7e2a3e33ffa9c415f91a6b76deb45", false, false] }' -H 'content-type: text/plain;' 0.0.0.0:5111`

For testnet SLP validator use:
- `docker build -t ec-slp-testnet .`
- `docker run -d -p 5112:5112 --restart "always" ec-slp-test`
- Test: `curl --data-binary '{"jsonrpc": "2.0", "id":"testing", "method": "slpvalidate", "params": ["5e9454840d838c81ac0c41f0754df239f1c1012623161359fbf6e22599605c25", false, false] }' -H 'content-type: text/plain;' 0.0.0.0:5112`

Skip steps 1 & 2 if you're using docker.

## 1) Initial Server Config Steps

1) Setup an Ubuntu vps.

2) Clone this project into the home directory (i.e. `~/`) & cd into the `Electron-Cash-SLP` directory.

3) Run the proper Electron Cash installation commands as described in the README for this project.

4) Open `~/.electron-cash/config` and set `rpcport` to some constant port number & `rpcpassword=""`.

5) Run `./elctron-cash create` to create a new wallet file.  This wallet should not be used to store any funds, it is only used to store SLP validation data for cache purposes.

## 2) Creating a persistent service with systemd

1) Copy the file named `slpvalidate.service` into `/lib/systemd/system/` directory.  Make sure the paths within the `slpvalidate.serice` file match the location of your Electron-Cash-SLP directory.

2) Run `sudo systemctl enable slpvalidate`

3) Run `sudo systemctl start slpvalidate`

4) Check that the service is running via `sudo systemctl status slpvalidate`

## 3) Setting up the reverse proxy server for this validation service.

1) Setup an nginx server per these instructions: https://linuxize.com/post/how-to-install-nginx-on-ubuntu-18-04/

2) Do an initial Setup for SSL via "Let's Enctypy" using these instructions but for your desired domain: https://linuxize.com/post/secure-nginx-with-let-s-encrypt-on-ubuntu-18-04/

3) Use the Nginx Server block file named `simpleledger.info`.  Update the contents of the file to reflect your specific domain / sub-domain. Rename the file to reflect your specific domain / sub-domain.  Then copy this file into your `/etc/nginx/sites-available/` directory.

4) Run `sudo ln -s /etc/nginx/sites-available/<your-domain> /etc/nginx/sites-enabled/`

5) Check that the syntax is all good: `sudo nginx -t`

6) Restart Nginx: `sudo systemctl restart nginx`

7) Test that the service is working via: `curl --data-binary '{"jsonrpc": "2.0", "id":"testing", "method": "slpvalidate", "params": ["2504b5b6a6ec42b040a71abce1acd71592f7e2a3e33ffa9c415f91a6b76deb45", false, false] }' -H 'content-type: text/plain;' https://validate.simpleledger.info`. Replace `validate.simpleledger.info` with your own domain.

## Other notes & warnings

* You can speed up your SLP validation server by also installing ElectrumX side-by-side and connecting to it directly.

* Running multiple instances of EC SLP using a load balancer can be accomplished using `electron-cash daemon --dir=<unuiqe-application-directory-per-instance>`, where the directory is just a copy of the `~/.electron-cash` directory.

* It should be noted that the Electron-Cash-SLP validator was not designed to be operated as a long running server application.  In this type of operation the validator object may cause memory useage issues as the number of validation requests increases.  Each time a new validation is performed the DAG and validation results are added to memory for caching purposes. Also, if the Electron-Cash-SLP daemon is not shut down via command-line, then the previously calculated validation results may not be written to the wallet file for future use.  Future improvements to the validator will need to fix these issues so that the validator can be run safely as a long running process.