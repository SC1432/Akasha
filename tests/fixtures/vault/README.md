# Fixture vault

Test data for pytest. Tests copy this folder to a temporary directory and `git init` it there; never point akashactl at this folder directly.

- `inbox/`: one Markdown article (with a prompt-injection line), a byte-identical copy under another name, a caption in a subfolder, three link styles (`.txt` URL, `.url`, `.webloc`), an uppercase-extension PNG, an empty file. The test fixture adds a `.DS_Store` at copy time, because the repo `.gitignore` excludes it.
- `personal/`: notes with YAML Akasha's parser refuses (nested mapping, `yes`), plus one with no frontmatter.
- `wiki/`: index, log, hot, and one valid concept and source page.
