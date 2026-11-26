# OpenAI Step 8 answer comparison

Previous answers, correctness scores, and latencies come from the frozen Step 1 comparison manifest. After answers, scores, and latencies come from the selected v2.17 Step 8 attempts. Correctness regressions are marked 🛑 in the question heading. OpenAI Q9 uses the approved item-specific scorer correction recorded in `factory-rubric-rescore-v2.json`; its raw evaluator score is shown in parentheses where it differs from the effective score.

**Mean correctness across 10 questions:** previous **0.8825** · after **0.93667** (using effective selected scores, including the approved Q9 rescore).

## Q1: What academic mathematics book does Lisbeth Salander carry around and memorize?

| | Previous (Step 1) | After (selected Step 8) |
|---|---|---|
| Answer | Lisbeth Salander carries *Dimensions in Mathematics*. She knows its text by heart and carries it as a physical link to Fermat [E1]. | Lisbeth Salander carries *Dimensions in Mathematics*, a 1,200-page book on the history of mathematics. She already knows it by heart; she carries it as a physical link to Fermat, almost like a talisman. [E2] [E1] |
| Correctness | 0.9 | 0.95 |
| Latency | 16.09s | 18.59s |
| Attempt | — | `openai-q01-a1` |

## Q2 🛑: Who killed Harriet?

| | Previous (Step 1) | After (selected Step 8) |
|---|---|---|
| Answer | No one killed Harriet: she was alive, and she told Mikael that Anita helped her escape Hedeby Island [E1] [E2]. | No one killed Harriet—she was alive. Anita helped her escape Hedeby Island and hide; Harriet says she went to Anita because she had to escape. [E1] |
| Correctness | 0.975 | 0.95 |
| Latency | 18.95s | 18.24s |
| Attempt | — | `openai-q02-a1` |

## Q3: What was the nickname of Mikael?

| | Previous (Step 1) | After (selected Step 8) |
|---|---|---|
| Answer | Mikael Blomkvist’s nickname was “Kalle Blomkvist.” [E1] | Mikael’s nickname was “Kalle Blomkvist.” [E1] |
| Correctness | 0.9167 | 0.9167 |
| Latency | 15.44s | 20.26s |
| Attempt | — | `openai-q03-a1` |

## Q4: Who are the top 10 most important characters?

| | Previous (Step 1) | After (selected Step 8) |
|---|---|---|
| Answer | The passages don’t establish a ranked top 10. They do support Lisbeth Salander and Mikael Blomkvist as central figures, and describe Erika Berger as an important counterpart at *Millennium* [E1] [E2]. | The novels don’t provide an official ranking, but a reasonable top 10 based on the passages here is:<br><br>1. Lisbeth Salander [E1]<br>2. Mikael Blomkvist [E1]<br>3. Henrik Vanger [E2]<br>4. Harriet Vanger [E3]<br>5. Martin Vanger [E4]<br>6. Erika Berger [E5]<br>7. Dragan Armansky [E5]<br>8. Bublanski [E5]<br>9. Zalachenko [E6]<br>10. Evert Gullberg [E7] |
| Correctness | 0.5 | 1 |
| Latency | 55.92s | 51.15s |
| Attempt | — | `openai-q04-a1` |

## Q5: How Gottfried really died?

| | Previous (Step 1) | After (selected Step 8) |
|---|---|---|
| Answer | Harriet escaped Gottfried, who had tried to strangle and rape her, and fled to the jetty. When he staggered after her, she shoved him into the water and held him under with an oar until he stopped struggling. [E2] [E1] | Harriet says she shoved Gottfried into the water and held him under with an oar until he stopped struggling. Martin was there afterward, when Gottfried was still floating in the water. [E1] [E2] |
| Correctness | 0.95 | 0.95 |
| Latency | 43.36s | 22.70s |
| Attempt | — | `openai-q05-a1` |

## Q6 🛑: what is the sumary of the first book?

| | Previous (Step 1) | After (selected Step 8) |
|---|---|---|
| Answer | Journalist Mikael Blomkvist, sentenced for libelling financier Hans-Erik Wennerström, takes Henrik Vanger’s assignment to uncover what happened to Harriet; Lisbeth Salander joins him as a research assistant. [E1][E2] Their investigation leads to Martin Vanger, who tries to kill Blomkvist, and reveals that Harriet is alive: she escaped with Anita and is living in Australia. [E3][E4][E5] | After receiving a prison sentence for libelling financier Hans-Erik Wennerström, Mikael Blomkvist takes Henrik Vanger’s job investigating Harriet’s disappearance and brings Lisbeth Salander in to help [46b8b531, 1bbd2040, f47a3981]. Their investigation leads to Martin Vanger’s basement and reveals his history of killing and raping; they ultimately learn that Harriet escaped and is alive in Australia [893923af, 214d23e5, 243a0459, 6807f97e]. |
| Correctness | 0.6333 | 0.6 |
| Latency | 41.45s | 49.82s |
| Attempt | — | `openai-q06-a1` |

## Q7: What happened to Teleborian in the end of the court?

| | Previous (Step 1) | After (selected Step 8) |
|---|---|---|
| Answer | Near the end of the hearing, Inspector Modig and Lisa Collsjö came into the courtroom, and Collsjö asked the judge’s permission to arrest Teleborian. She arrested him for violating the law on child pornography after about nine thousand pornographic pictures of children were found on his computer; his laptop was seized and he was led away. [E1] [E2] [E3] | During Salander’s trial, Edklinth testified that Teleborian’s psychiatric report was a sham, and the judge warned Teleborian that he risked a perjury charge. Police then arrested him in the courtroom for possessing about nine thousand child-pornography photographs on his computer and confiscated his laptop; he was led away as Salander watched. [E1] [E2] [E3] [E4] |
| Correctness | 0.95 | 1 |
| Latency | 27.84s | 26.33s |
| Attempt | — | `openai-q07-a1` |

## Q8: How Mikale knows that Salander is a hacker?

| | Previous (Step 1) | After (selected Step 8) |
|---|---|---|
| Answer | He realized it when Salander’s report reproduced wording from a press release that existed only on his personal iBook; it had never been printed, and even Berger had no copy. Blomkvist concluded Salander had accessed his computer and called her “a fucking hacker.” [E1] [E2] | While reading Salander’s report, Blomkvist recognized wording from a press release that existed only on his private iBook. He concluded that she had been inside his computer and said, “You’re a fucking hacker.” [E1] [E2] |
| Correctness | 1 | 1 |
| Latency | 19.78s | 32.95s |
| Attempt | — | `openai-q08-a3` |

## Q9: What happened to Salander in the abandoned factory?

| | Previous (Step 1) | After (selected Step 8) |
|---|---|---|
| Answer | Salander found bodies in a pool inside the brickworks, then discovered Niedermann hiding there; he locked her in with him. They fought, and she escaped the building, left a knife behind, lured Nieminen’s gang there, and alerted the police. [E1] [E2] [E3] [E4] [E5] [E6] | Salander found Niedermann living in the abandoned brickworks, then realized the exit was padlocked and he had trapped her inside. She fought back with a crowbar and fled into the inner workshop; later, after she alerted the police and drew Svavelsjö MC to the site, Niedermann was killed by the gang, while Salander was outside and safe [E1] [E2] [E3] [E4] [E5] [E6] [E7] [E8]. |
| Correctness | 1 | 1 (raw evaluator: 0.5167) |
| Latency | 40.53s | 41.12s |
| Attempt | — | `openai-q09-a1` |

## Q10: When Mikael Blomkvist found Lisbeth Salander severely wounded on the kitchen bench at the Gosseberga farmhouse, he reached out to carefully loosen the gun from her hand. And then what Salander said to him?

| | Previous (Step 1) | After (selected Step 8) |
|---|---|---|
| Answer | She muttered, “Kalle Fucking Blomkvist.” [E1] | She muttered, “Kalle Fucking Blomkvist.” [E1] |
| Correctness | 1 | 1 |
| Latency | 14.86s | 17.72s |
| Attempt | — | `openai-q10-a2` |
