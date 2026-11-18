# Why did Mikael agree to work for Henrik?

Mikael agreed primarily because Henrik promised information that would expose Wennerström. Henrik also offered him 200,000 kronor a month, or 2.4 million kronor for a full year, to investigate Harriet’s disappearance.

## Retrieval steps

This was not a blind investigation. An earlier evaluator comment in the conversation had already mentioned Wennerström and the salary, and that information influenced the later search terms. The answer is supported by the indexed passages below.

1. **`keyword_search`** for `Mikael Henrik work offer agreement`, with `k=10`. Results included passages about the agreement and later consequences, but did not establish the original reason for taking the job.
2. **`keyword_search`** for `Blomkvist Vanger offer investigate Harriet employment`, with `k=10`. Results included the initial job approach and later discussion of the employment, but did not directly answer why Mikael accepted.
3. **`keyword_search`** for `Henrik Blomkvist job salary offer Wennerström`, with `k=10`. This returned `4d64f811`, describing the salary offer, and `c3dafc44`, where Henrik says Mikael took the job because of the promise to expose Wennerström.
4. **`keyword_search`** for `Vanger Blomkvist investigation offer kronor`, with `k=10`. This also returned `4d64f811`.
5. **`read_passage` on `4d64f811`**, with three neighbors on each side. This confirmed the salary and returned `a54205ec`, which describes the proposed investigation into Harriet’s disappearance.
6. **`read_passage` on `c3dafc44`**, with three neighbors on each side. This confirmed Henrik’s account of Mikael’s reason for taking the job and the timing of the promised information.

## Source passages in chronological order

### `a54205ec` — *The Girl with the Dragon Tattoo*, chapter 6, paragraph 96

The neighboring result was truncated by the retrieval tool:

> Blomkvist sighed. He was feeling more and more uncomfortable and wanted to end this visit to Hedeby, but he relented. “All right, let’s hear it.” “I want you to live and work here in Hedeby for a year. I want you to go through the investigative report on Harriet’s disappearance one page at a time. I want you to examine everything with new eyes. I want you to question all the old conclusions exactly the way an investigative reporter would. I want you to look for something that I and the police an…

### `4d64f811` — *The Girl with the Dragon Tattoo*, chapter 6, paragraph 99

> “You’re asking me to set aside my life and career to devote myself for a whole year to something that’s a complete waste of time.” Vanger smiled. “As to your career, we might agree that for the moment it’s somewhat on hold.” Blomkvist had no answer to that. “I want to buy a year of your life. Give you a job. The salary is better than any offer you’ll ever get in your life. I will pay you 200,000 kronor a month—that’s 2.4 million kronor if you accept and stay the whole year.”

### `c3dafc44` — *The Girl with the Dragon Tattoo*, chapter 8, paragraph 68

> Vanger looked over towards the bridge. He was a gaunt man, and Blomkvist thought that he looked at that moment like a melancholy scarecrow. “As far as Millennium is concerned, we ought to have a discussion about what kind of crisis it’s in and whether I can help in some way.” “The best assistance you can offer is to give me Wennerström’s head on a platter right here and now.” “Oh no, I’m not thinking of doing that.” The old man gave Blomkvist a hard look. “The only reason you took this job was because I promised to expose Wennerström. If I give you the information now, you could stop work on the job whenever you felt like it. I’ll give you the information a year from now.”
