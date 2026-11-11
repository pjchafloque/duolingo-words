# Plan B: manual imports

If the automatic sync stops working, open `tools.html` on your site, drag the
export button to your bookmarks bar, and click it while you're on
duolingo.com/practice-hub/words. It downloads a `.json` file with your words.

Upload that file here (Add file → Upload files → Commit). The workflow runs on
its own, merges the words into `data/words.json`, and updates the page.
Each file is only imported once, so you can leave old ones here.
