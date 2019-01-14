# SLP Token Validation Proxy Server

Electron-Cash-SLP can be run in daemon mode to serve token validation requests using JSON RPC interface.  The following instructions explain how to set this up using an Ubuntu server with nginx reverse proxy server. 

## Initial Server Config Steps

1) Setup an Ubuntu server

2) Clone this project into your home directory (i.e. `~/`) & cd into the `Electron-Cash-SLP` directory.

3) Run the proper Electron Cash installation commands as described in the readme for this project.

4) Run `./elctron-cash create` to create a new wallet file.  This wallet shouldn't be used to store any funds, it is only used to store SLP validation data for cache purposes.

## Creating a persistent service with systemd

1) Copy the file named `slpvalidate.service` into `/lib/systemd/system/` directory.  Make sure the paths within the `slpvalidate.serice` file match the location of your Electron-Cash-SLP directory.

2) Run `sudo systemctl start slpvalidate`

3) Check that the service is running via `sudo systemctl status slpvalidate`

## Setting up the reverse proxy server for this validation service.

1) Setup an nginx server per these instructions: https://linuxize.com/post/how-to-install-nginx-on-ubuntu-18-04/

2) Do an initial Setup for SSL via "Let's Enctypy" using these instructions but for your desired domain: https://linuxize.com/post/secure-nginx-with-let-s-encrypt-on-ubuntu-18-04/

3) Use the Nginx Server block file named `simpleledger.info`.  Update the contents of the file to reflect your specific domain / sub-domain. Rename the file to reflect your specific domain / sub-domain.  Then copy this file into your `/etc/nginx/sites-available/` directory.

4) Run `sudo ln -s /etc/nginx/sites-available/<your-domain> /etc/nginx/sites-enabled/`

5) Check that the syntax is all good: `sudo nginx -t`

6) Restart Nginx: `sudo systemctl restart nginx`

7) Test that the service is working via: `curl --data-binary '{"jsonrpc": "2.0", "id":"testing", "method": "slpvalidate", "params": ["2504b5b6a6ec42b040a71abce1acd71592f7e2a3e33ffa9c415f91a6b76deb45", false, false] }' -H 'content-type: text/plain;' https://validate.simpleledger.info`. Replace `validate.simpleledger.info` with your own domain.

## Other notes

You can speed up your SLP validation server by also installing ElectrumX side-by-side and connecting to it directly.


