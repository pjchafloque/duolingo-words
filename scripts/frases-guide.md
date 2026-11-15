# Daily review of the important sentences

This is what the daily review follows to keep the "Frases importantes" tab growing. It runs once a day as a scheduled Claude task, and anyone can follow it by hand too. The goal is that every new Duolingo unit and every batch of new words ends up as sentences with a situation, a note and, for the must-knows, a star, the same way the first groups were written.

The reader is a beginner who speaks Spanish and is getting ready to live abroad as a student. A sentence is important when he'll actually say it or hear it in daily life there: greeting people, ordering, introducing himself, talking about his family, and so on.

## Steps

1. Run `python3 scripts/frases.py --todo`. If it says "Nothing new", stop there and don't commit anything.

2. Put every key phrase it lists into a group in `data/frases.json`, under `"fr"` → `"groups"`. These come from Duolingo's Guidebook, so all of them go in.
   - Use an existing group when the situation fits (Saludos y despedidas, Presentarse, En el café...). Otherwise start a new group at the end of the list with a short Spanish title for the situation, like "La familia" or "En la estación", and an `id` in lowercase letters, digits and dashes (`familia`, `estacion`).
   - Copy `fr` exactly as `--todo` shows it, including the space before `?` and `!`, so the page can match it with Duolingo's recording. Take `es` from Duolingo too; fix it only if the Spanish reads wrong.

3. Write new sentences with the words `--todo` lists as learned since the last review.
   - Only use words from "Your whole notebook", which `--todo` prints. A phrase from the notebook counts as a whole ("s'il vous plaît", "je m'appelle"), but its parts don't count on their own: "habite" alone isn't in the notebook just because "elle habite" is. Names of people and cities are fine, but never as the first word of the sentence.
   - Write about one sentence for every three or four new words, at most eight in one review. A word that doesn't lead to a useful sentence (an interjection like "oh", say) can be left out.
   - Each sentence should be something a person really says. Skip textbook lines that only show off vocabulary. A question paired with its answer works well.
   - Put each one in the group of its situation, next to the sentences it goes with. Don't repeat a sentence that's already there.

4. Fill in each new sentence, the same way the existing ones are written:
   - `fr`: the sentence, with French spacing before `?` and `!`.
   - `es`: what it means, in natural Spanish with ¿ and ¡.
   - `use`: one or two short sentences in Spanish about when to use it, plus anything that trips up a Spanish speaker (tú or usted, a word's gender, a letter that doesn't sound, a word to swap for your own). Write plainly, the way a friend would explain it. No long dashes: use a comma or a period.
   - `star`: `true` only for the must-knows, the ones you'd need in your first week abroad. Two or three per group is usual; most sentences don't get one.
   - `added`: today's date, like `"2026-11-15"`. The page marks the sentence "nueva" for 7 days.

5. Set `"words_reviewed"` to the number at the end of `--todo` ("set words_reviewed to ...").

6. Run `python3 scripts/frases.py --check` and fix whatever it reports until it says "All good."

7. Commit only `data/frases.json`, with a message like "Add important sentences: La familia", and push to `main`. If the push is rejected because the sync pushed first, run `git pull --rebase origin main` and push again. The push runs the sync, which writes how each new sentence reads and republishes the page a minute or two later.

## Don't

- Don't change or delete sentences that are already in `data/frases.json`. Pablo may have edited them by hand, and his version wins.
- Don't edit other files. The sync writes `data/guidebook.json`, `data/words.json` and `data/frases-pron.json` on its own.
- Don't invent key phrases or mark a sentence as Duolingo's. Only the ones in `data/guidebook.json` play Duolingo's recording; the page works that out by itself.
