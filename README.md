# duolingo-words

My French notebook: every word I've learned on Duolingo, with its meaning, how it sounds written with Spanish letters, and a button to hear it. It updates itself every 6 hours.

Page: https://pjchafloque.github.io/duolingo-words/

## Setup (once)

1. Turn on GitHub Pages. In this repo, open Settings → Pages. Under "Build and deployment", change Source to "GitHub Actions".

2. Add your Duolingo token.
   - In Chrome, open duolingo.com and check that you're logged in.
   - Open DevTools (Cmd + Option + I on a Mac). Go to the Application tab, then Storage → Cookies → `https://www.duolingo.com`.
   - Find the row named `jwt_token` and copy its value, a long string with two dots in it.
   - In this repo, open Settings → Secrets and variables → Actions → "New repository secret". Name it `DUOLINGO_JWT`, paste the value and click "Add secret".

   The token works like a password for your Duolingo account, so paste it only into that secret box. It keeps working until you change your Duolingo password.

3. Run it. Open the Actions tab, click "Sync words" on the left, then "Run workflow". A minute or two later the page is live at the address above.

## How it works

- `.github/workflows/sync.yml` runs `scripts/sync.py` every 6 hours, and also whenever something in the repo changes.
- `sync.py` asks Duolingo for the same list you see at duolingo.com/practice-hub/words. New words go into `data/words.json` with the date the sync first saw them. Words you already had when this started are grouped as "Jusqu'au …" (up to that date).
- `scripts/pronounce.py` writes the pronunciations. eSpeak NG, a free speech program, gives the sounds, and a table turns them into Spanish spelling with Spanish accent rules: `bonjour` becomes "bonyur", `merci` becomes "mersí", `croissant` becomes "cruasán".
- `index.html` is the page. The play button uses Duolingo's own recording of the word, or your browser's French voice when there isn't one. "Repaso" covers the meanings so you can quiz yourself, and "Lento" slows the audio down.

Duolingo has no official API. This uses the same requests the Duolingo website makes, so it can stop working if Duolingo changes them. Duolingo's terms also say content shouldn't be downloaded or scraped, so strictly speaking this breaks them. It only reads your own list, a few times a day. The page is public, so anyone with the link can see your word list. The token is never on the page.

## Fixing a pronunciation

Edit `data/overrides.json` on GitHub (the pencil icon) and add the word under `"fr"`:

```json
"fr": {
  "bonjour": "bonshur",
  "chat": {"pron": "sha", "note": "la t no suena"}
}
```

A plain string replaces the pronunciation. You can also set `translations` (a list) and a `note`. Saving runs the sync, and the page updates a minute or two later.

To change how a sound is written everywhere, for example the French "j" as "sh" instead of "y", edit the tables at the top of `scripts/pronounce.py` and add 1 to `VERSION`.

## Plan B: exporting by hand

If the automatic sync stops working, the page shows the reason in red. Open `tools.html` on your site and follow its three steps: drag a button to your bookmarks bar, click it on Duolingo's Words page, and upload the file it downloads to `data/import`.

## When something goes wrong

- "Duolingo rejected the token": copy a fresh `jwt_token` (step 2) and update the secret.
- "Duolingo answered with a web page instead of data": Duolingo is blocking GitHub's servers. Use plan B.
- The page stopped updating and the Actions tab says the workflow is disabled: GitHub pauses scheduled runs after 60 days without changes to the repo. Click "Enable workflow".
- Each run's log (Actions tab → the run → "sync") explains what happened.
