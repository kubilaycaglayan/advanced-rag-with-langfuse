# Who helped Mikael decode Harriet’s diary numbers?

Mikael’s daughter, **Pernilla**, helped him decode the numbers. She recognized the writing on his wall as Bible quotations. Her comment prompted Mikael to check Harriet’s Bible, where he realized that the numbers referred to chapters and verses in Leviticus.

## Retrieval steps

The following pipeline tools were used against the indexed corpus:

1. **`keyword_search`** — searched for `Harriet diary numbers Bible Mikael`. Among the results were passage `74edfbe8`, which identifies Pernilla as Mikael’s daughter, and `3168fdf0`, which says the numbers were references to Leviticus.
2. **`read_passage` on `74edfbe8`**, with three neighboring passages on each side — established Pernilla’s relationship to Mikael and found their conversation near the railway station.
3. **`read_passage` on `3168fdf0`**, with three neighbors on each side — confirmed that the numbers indicated chapters and verses in Leviticus. A preceding passage, `bc3dc196`, contained Pernilla’s comment about quotations on Mikael’s wall.
4. **`read_passage` on `fb008caa`**, with three neighbors on each side — showed that Mikael returned to the note containing the numbers and fetched Harriet’s Bible.
5. **`read_passage` on `bc3dc196`**, with one neighbor on each side — checked the comment in context: Pernilla says she saw the quotations, and Mikael understands its significance after her train departs.

The evidence comes from *The Girl with the Dragon Tattoo*, chapter 17, passages `74edfbe8`, `bc3dc196`, `fb008caa`, and `3168fdf0`.


## Source passages in chronological order

### `74edfbe8` — Chapter 17, paragraph 74

> “Why are you going to Skellefteå?” “Bible school at a summer camp with a congregation called the Light of Life,” Pernilla said, as if it were the most obvious choice in the world. Blomkvist felt a cold fire run down the back of his neck. He realised how alike his daughter and Harriet Vanger were. Pernilla was sixteen, exactly the age Harriet was when she disappeared. Both had absent fathers. Both were attracted to the religious fanaticism of strange sects—Harriet to the Pentecostals and Pernilla to an offshoot of something that was just about as crackpot as the Word of Life.

### `bc3dc196` — Chapter 17, paragraph 86

> “Why do you say that?” “I saw the quotes you had on the wall,” she said. “But why so gloomy and neurotic? Kisses. See you later.” She waved and was gone. He stood on the platform, baffled, watching the train pull away. Not until it vanished around the bend did the meaning sink in. Mikael hurried out of the station. It would be almost an hour before the next bus left. He was too much on edge to wait that long. He ran to the taxi stand and found Hussein with the Norrland accent.

### `fb008caa` — Chapter 17, paragraph 90

> Ten minutes later he was in his office. He had taped the note above his desk. Magda—32016 Sara—32109 R.J.—30112 R.L.—32027 Mari—32018 He looked around the room. Then he realised where he’d be able to find a Bible. He took the note with him, searched for the keys, which he had left in a bowl on the windowsill, and jogged the whole way to Gottfried’s cabin. His hands were practically shaking as he took Harriet’s Bible down from its shelf.

### `3168fdf0` — Chapter 17, paragraph 93

> She had not written down telephone numbers. The figures indicated the chapter and verse in Leviticus, the third book of the Pentateuch. He went out and sat on the porch. Each verse had been underlined in Harriet’s Bible. He lit a cigarette and listened to the singing of birds nearby. He had the numbers. But he didn’t have the names. Magda, Sara, Mari, R.J., and R.L. All of a sudden an abyss opened as Mikael’s brain made an intuitive leap. He remembered the fire victim in Hedestad that Inspector Morell had told him about. The Rebecka case, which occurred in the late forties. The girl was raped and then killed by having her head placed on smouldering coals. “And he shall cut it into pieces, with its head and its fat, and the priest shall lay them in order upon the wood that is on the fire upon the altar.” Rebecka. R.J. What was her last name?
