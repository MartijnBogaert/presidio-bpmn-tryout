# Finding personal data in BPMN diagrams: what we tried and what we learned

Process diagrams in Open Proces Huis sometimes contain personal data: a name in a lane, a phone number in a task, a
rijksregisternummer in a note. Before a diagram is shared, that data should be found and masked (replaced by
`*****`). The [pii-identification-anonymization-service](https://github.com/lblod/pii-identification-anonymization-service)
does this with **Presidio**, an open-source toolkit for finding personal data.

This experiment asked: **how well does that work today, and how can we make it better?**

All examples below come from the test diagrams. Every name, number and address in them is made up.

---

## 1. How we tested

### Test diagrams with a known answer

To measure how good detection is, you need diagrams where you already *know* where all the personal data is. So we
generated 20 realistic Dutch process diagrams (rijbewijs aanvragen, fuifkwaliteitslabel, omgevingsvergunning,
leefloon, …) and hid **205 pieces of personal data** in them, in all the places where real people write things:

| Where | Example |
|---|---|
| Task name | `Doorsturen naar Lander Lambrecht` |
| Lane name | `Tom - Burgerzaken` |
| Documentation of a task | `Aanvrager Nele Vandenberghe, wonende te Veldstraat 153, 3500 Hasselt, geboren op 19-08-1960, rijksregisternummer 600819 817 26.` |
| Note (text annotation) | `Telefoon Nele Vandenberghe: +32 480 33 72 37` |

We also added things that **look like** personal data but are not, to see whether the system raises false alarms:
municipality names ("Gemeente Gent"), roles ("Schepen van Jeugd"), deadlines ("Uiterlijk 31 augustus"), case numbers
("20240315001") and typical OPH jargon ("DOSIS", "GaNaar", "Afgerond").

### What we measured

Take the task `Doorsturen naar Lander Lambrecht`. Possible outcomes:

| Outcome | After masking | What it means |
|---|---|---|
| Fully covered | `Doorsturen naar *****` | perfect |
| Partly covered | `Doorsturen naar Lander *****` | found, but the first name still leaks |
| Missed | `Doorsturen naar Lander Lambrecht` | not found at all |
| False alarm | `***** opvragen` for `Adviezen opvragen` | something that is not personal data is masked |

From this we report four numbers:

- **Precision**: of everything the system flags, how much is really personal data? (Few false alarms means high precision.)
- **Fully covered**: how much of the personal data is completely masked?
- **Left after anonymizing**: how much personal data can still be (partly) read in the masked diagram? *This is the
  number that matters most for privacy.*
- **False alarms**: items a reviewer has to dismiss by hand.

---

## 2. Where we started: the current service

| | Current service |
|---|---|
| Precision | 0.62 (more than 1 in 3 alarms is false) |
| Fully covered | 39% |
| **Left after anonymizing** | **60%** |

Why so low? Mainly four reasons:

1. **It only reads element names.** Documentation and notes are never checked, and that is where the longest texts,
   and much of the personal data, are. `Aanvrager Nele Vandenberghe, wonende te …` stays untouched.
2. **It doesn't know Belgian formats.** A phone number like `0471 12 34 56` is cut into pieces and labelled as a
   *date*. A rijksregisternummer written with spaces (`670620 907 39`) is missed, so
   `Rijksregister 050407 786 39 opvragen` becomes `Rijksregister 050407 ***** 39 opvragen`.
3. **It flags ordinary words.** Town names and capitalized Dutch words are taken for places or names:
   `Jeugd - Fuifkwaliteitslabel aanvraag Aalter` became `Jeugd - ***** aanvraag *****`.
4. **Names are cut in half.** `Lander Lambrecht` becomes `Lander *****`.

---

## 3. What we improved, step by step

We added improvements one at a time and measured after each step. The first six came from the team's list of ideas;
the rest followed from what the measurements showed.

| Step | What it does | Example |
|---|---|---|
| 1. Only relevant types | Stop looking for dates, nationalities, URLs, … | "31 augustus" is no longer flagged |
| 2. Score thresholds | Require more confidence for names | **No effect**: the language model gives every name the same score (0.85), so there is nothing to set a threshold on |
| 3. Allow-list | A list of known jargon that is never personal data | "Herinnering", "DOSIS", "Moraliteitsonderzoek" no longer flagged |
| 4. Checksum for the rijksregisternummer | A real number has check digits; check them | the case number `20240315001` is no longer taken for a rijksregisternummer |
| 5. Acronym rule | Short all-caps words are not names | **No measurable effect** on our test set |
| 6. No duplicates | Show each value once to the reviewer, mask it everywhere | an email address that appears in three places is on the review list once, and masked in all three |
| 7. Read documentation and notes | Also scan the longer texts | the biggest single gain |
| 8. Belgian recognizers | Belgian phone numbers, rijksregisternummer with spaces, company number (KBO), license plate (`1-ABC-234`), addresses, birth dates | `0471/12.34.56`, `0700.775.411`, `Veldstraat 11, 8800 Roeselare` are now found |
| 9. Stop looking for places | Full addresses are now found by step 8; town names on their own are rarely personal data | 30 false alarms gone ("Sint-Niklaas", "Huwelijksboekje") |
| 10. Complete multi-part names | Extend a name over *van, de, el, …* | `Yusuf El` → `Yusuf El Amrani`, `Velde` → `Elke Van de Velde` |
| 11. Mask name parts everywhere | Once "Lander Lambrecht" is approved, mask "Lander" on its own too | `Lander - Burgerzaken` → `***** - Burgerzaken` |

**Result after all steps:**

| | Current service | After all steps |
|---|---|---|
| Precision | 0.62 | 0.95 |
| Fully covered | 39% | 98% |
| **Left after anonymizing** | **60%** | **1.5%** |
| False alarms | 62 | 10 |

The two steps that mattered most were **reading documentation and notes** (step 7) and **knowing Belgian formats**
(step 8). The steps against false alarms that helped most were **only relevant types** (step 1) and **stop looking for
places** (step 9).

A side finding: when the current service hesitates between two types with exactly the same score (say "date" or
"rijksregisternummer" for the same number), it picks one **at random**, and may pick differently on the next run. The
improved version always makes the same choice.

---

## 4. Does it help to give the model the whole diagram at once?

So far, every label was checked **on its own**: 551 separate checks for our 20 diagrams. A label like `Adviezen`
gives the model nothing to go on, and so many separate checks are slow. The alternative is to turn a diagram into
**one text** and check it once:

```
Taak: Terugbetaling op BE32 5678 9073 9102.
Beslissing: Aanvraag volledig?
Taak: Controle RRN 60121670958.
Lane: Tom - Burgerzaken.
```

We even tried telling it as a **story**, in the order of the process:

```
Het proces begint met: 1 maand voor de fuif.
Stap 1: Terugbetaling op BE32 5678 9073 9102.
Daarna volgt de beslissing: Aanvraag volledig?
Bij antwoord Ja gaat het verder met stap 2.
```

What we found with the **current language model** (md); section 5 repeats this test with the other models:

- **One text is 3–4× faster** (one check per diagram instead of one per label) and gives **fewer false alarms**: in a
  sentence, "Adviezen" and "Opgelet" are no longer mistaken for names.
- **But some names in short labels get lost.** On its own, `Tom - Burgerzaken` is recognized as a person. Between
  lanes like "Jeugddienst" and "Schepencollege", the model thinks it is an *organisation*, and
  `Dossier Marleen Jacobs` even becomes a *title of a work* (like a book).
- **The order and the story make no difference, or make it slightly worse.** The current model only looks at a
  few words around each word, so it never "reads" the diagram as a whole. Even right after
  "Betrokken in dit proces: Tom Lemmens.", it still doesn't see that "Tom - Burgerzaken" is a person.

---

## 5. Does a bigger or smarter language model help?

The part that recognizes names is a **language model**. We compared three:

| Model | In plain words |
|---|---|
| **md** (current) | A quick reader with a small vocabulary. Looks at a few words at a time. 55 MB. |
| **lg** | The same quick reader with a much bigger vocabulary. 631 MB, just as fast. |
| **transformer** (BERTje) | A careful reader that takes in the whole sentence at once, the same family of technology as modern AI chatbots, but small and trained only to spot names. 0.5 GB, about 10× slower on a normal computer. |

Results with all improvements switched on:

| Model | How the text is given | Precision | Fully covered | **Left after anonymizing** | False alarms | Time for 20 diagrams |
|---|---|---|---|---|---|---|
| md | per label | 0.95 | 98% | 1.5% | 10 | ≈2 s |
| md | one text | 0.99 | 94% | 2.0% | 2 | ≈0.5–1 s |
| lg | per label | 0.99 | 96% | 2.0% | 2 | ≈2 s |
| lg | one text | 1.00 | 96% | 2.0% | 0 | ≈0.5–1 s |
| lg | story | 0.99 | 97% | 2.4% | 3 | ≈0.7 s |
| transformer | per label | 0.98 | 95% | **0.5%** | 5 | ≈19 s |
| transformer | one text | 0.93 | 94% | 1.5% | 14 | ≈5 s |
| transformer | story | 0.93 | 93% | 1.5% | 15 | ≈8 s |

All three models were tested with every way of giving the text (per label, one text, one text with element types,
flow order, story), with all improvements switched on; the table shows the most telling combinations. The full table
is in notebook `03_models.ipynb`.

- **The bigger vocabulary (lg)** mostly means fewer false alarms, at the same speed. It also recognizes
  `Tom - Burgerzaken` as a person, even inside a story.
- **The careful reader (transformer)** leaves the least personal data behind when it checks **label by label**: 0.5%.
  It finds names the others miss (`Doorsturen naar Lander Yilmaz`). The price: it is about 10× slower without a
  graphics card.
- **Giving the transformer the whole diagram at once does not help it.** One text is about 3–4× faster for it too,
  but it raises many more false alarms (14 instead of 5): between other lines, lane and role names like "Burger",
  "Brandweer" and "Melder", and even the title "dhr." in "dhr. Janssens", look like persons to it. More personal data
  is also left behind (1.5% instead of 0.5%). The story does not change that.
- **So the "whole diagram" idea works best with lg**: no false alarms in one text, and the story covers the most of
  all one-text options (97%).
- **A configuration pitfall:** the transformer splits rare words into pieces ("Huysmans" → "Huys" + "mans"). With the
  standard setting, it often forgot the second piece and found only "Annelies" in "Annelies Huysmans". With the right
  setting, it finds the full name. This one setting made the difference between 84% and 95% fully covered.

---

## 6. So what should we do?

There is no single winner. It depends on what matters most:

| If the priority is… | Choose | Because |
|---|---|---|
| leaking as little as possible | transformer, per label | only 0.5% left, but slower (≈1 s per diagram) |
| a short, clean review list, cheaply | lg, one text | no false alarms, one check per diagram |
| a simple step up from today | md (current model), per label, with all improvements | already goes from 60% to 1.5% left |

Whatever the choice, **the improvements of section 3 are what make the big difference.** Going from 60% to 1.5% left
comes from them, not from the model.

---

## 7. What to keep in mind

- **The test diagrams are made up.** The Belgian recognizers were written in the same experiment as the test
  diagrams, so they "know" the formats used. Real diagrams will be messier. **The most important next step is testing
  on real (anonymized) OPH diagrams.**
- **First names on their own** ("Marleen - Burgerzaken") remain the hardest case. A list of common first names in
  Belgium could help, whichever model is used

---

*Details, code and all numbers: see the notebooks in this folder (start with `04_overview.ipynb`) and the
[README](README.md).*
