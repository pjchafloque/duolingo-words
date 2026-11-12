# duolingo-words

My language notebooks: every word I've learned on Duolingo, in French and Portuguese, with its meaning, how it sounds written with Spanish letters, and a button to hear it. Each course has its own tab, and the page updates itself every hour.

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

## On your iPhone

Open the page in Safari, tap Share, then "Add to Home Screen". It gets the owl-and-penguin icon and opens like an app, without Safari's address bar.

## How it works

- `.github/workflows/sync.yml` runs `scripts/sync.py` every hour, and also whenever something in the repo changes.
- `sync.py` asks Duolingo for the same list you see at duolingo.com/practice-hub/words. New words go into `data/words.json` with the date the sync first saw them. Words you already had when this started are grouped as "Jusqu'au …" (up to that date).
- `scripts/pronounce.py` writes the pronunciations. eSpeak NG, a free speech program, gives the sounds, and a table turns them into Spanish spelling with Spanish accent rules: `bonjour` becomes "bonyur", `merci` becomes "mersí", `croissant` becomes "cruasán".
- `index.html` is the page, including the class notebook (see below). The play button uses Duolingo's own recording of the word, or your browser's French voice when there isn't one. "Repaso" covers the meanings so you can quiz yourself, and "Lento" slows the audio down.

Duolingo has no official API. This uses the same requests the Duolingo website makes, so it can stop working if Duolingo changes them. Duolingo's terms also say content shouldn't be downloaded or scraped, so strictly speaking this breaks them. It only reads your own list, a few times a day. The page is public, so anyone with the link can see your word list. The Duolingo token is never on the page.

## French and Portuguese

Duolingo only shares the word list of the course that's open in your app, so each run reads that one course. To bring in new Portuguese words, open Portuguese on Duolingo and either wait for the next hourly run or press "Sincronizar ahora" on the page. That opens the workflow on GitHub, where you click "Run workflow". Switching courses never loses words: each notebook keeps everything it has seen, and new words show up with the date a run first found them.

The Portuguese tab shows up as soon as a run reads your course list, even before its words arrive. `data/notebooks.json` decides which courses get a tab. Your account also has English and Chinese; add `"en"` or `"zh"` to its list to see them too. Each notebook has its own paper, school cursive and pronunciation guide. Linking to `…/duolingo-words/#pt` opens the Portuguese one directly.

## The class notebook (Aula)

The Portuguese notebook has two divider tabs under its title: "Duolingo" (the words above) and "Aula", what I learned in class (PORT 12200, Portuguese for Spanish Speakers, and Portuguese for the Profession). Aula is organized by topic, and every card says which class it came from:

- Vocabulário: the class words by theme, with pronunciation and audio. A ✓ means the word is also in my Duolingo list, and those play Duolingo's recording.
- Verbos: a card per tense (endings in red, when to use it, how Spanish differs) and "Buscar um verbo", which shows any class verb in every tense, with irregular forms in red.
- Gramática, Cuidado! (false friends, nouns that change gender, sounds, typical mistakes), Negócios and Cultura (each class's opening question with a sample answer, plus culture notes).
- Praticar: fill-in exercises and a random conjugation drill.

The lesson menu in the toolbar shows everything from one class at once, and the search looks through all of Aula (a conjugated form like "fizemos" finds "fazer"). "Repaso" covers meanings and verb forms. Direct links: `…/duolingo-words/#aula`, `#aula/verbos`, `#aula/praticar`.

Everything comes from `data/aula.json`, written by hand. To add a word, find its topic under `sections` → `vocabulario` and add a line like `["a praia", "la playa"]` (a third item is a note). Verbs go in `verbs` as `{"v": "falar", "es": "hablar", "lessons": ["d2"]}`. On each run, `scripts/aula.py` conjugates the verbs into `data/aula-verbos.json` and writes the pronunciations into `data/aula-pron.json` with the same eSpeak converter as the Duolingo words. Irregular verbs are listed in that script.

## Fixing a pronunciation

### From the page

On a device where your GitHub token is saved, the toolbar has an "Editar" button. Turn it on, tap a blue pronunciation, type how the word sounds and press Enter. The page saves the fix to `data/overrides.json` as a commit, which runs the sync, and the public page shows it a minute or two later. Your own device shows it right away. Leave the box empty to get the automatic pronunciation back. It also works on the Aula vocabulary.

Only you can save. The page is static, so it has no way to check a password, but every save is a write to this repo, and GitHub only takes writes from you. The page makes them with a fine-grained GitHub token that only opens this repo. To set it up:

1. On the page, click "Editar pronunciaciones" at the bottom. The box that opens has a link to GitHub with the token's name and permission already filled in.
2. On GitHub, under "Repository access", pick "Only select repositories" and choose duolingo-words. Check that Contents says "Read and write", generate the token and paste it into the box.

Do this once on each device. On the iPhone, paste it inside the Home Screen app, because that app keeps its data apart from Safari (copying on the Mac and pasting on the iPhone works with Universal Clipboard). The token stays in that browser's storage and is only sent to api.github.com. Visitors don't have it, so they never see the Editar button, and GitHub would refuse a change from anyone else anyway.

To stop editing on one device, click "Quitar el token de este dispositivo" at the bottom of the page. To turn it off everywhere, delete the token on GitHub (Settings → Developer settings → Personal access tokens). If GitHub stops accepting the token, the page asks for a new one.

### By hand

Edit `data/overrides.json` on GitHub (the pencil icon) and add the word under its course, `"fr"` or `"pt"`:

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
