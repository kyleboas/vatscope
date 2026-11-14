# Deploying

GitHub `main` is the source of truth for this repo, even though the coding server serves it.
To deploy, push to `main`. Coding pulls it within a minute and restarts the site (vatscope-update timer, set up by deploy/install-service.sh).
Don't rsync or scp code to coding, edit files there, or pull and restart by hand.
A checkout on coding with local edits is skipped, not overwritten, so leave those checkouts clean.
