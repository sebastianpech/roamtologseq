# Roam to Logseq
The script loads a json export of a Roam graph and cleans it up for import into Logseq.

## Performed actions

1. **Turn all roam queries into inline code.** Works with multiple queries at arbitrary locations inside a block.
2. **Download all files stored in roam and relink them for placement in the assets folder** (This will take a while, files are only downloaded once)
3. **Rename roam attributes**. A given set of attributes is turned into logseq properties, all other are renamed to `[[name]]:`
4. **Schedule blocks with a given tag**. If a block contains a given tag flagging it for scheduling, the first found date reference is added as a logseq scheduled property.
5. **Convert given task management tags to logseq task markers**. Eg. `#waiting` becomes `WAITING`, or `#canceled` becomes `CANCELED`