# Research proposal

*Quantifying Expansion Anisotropy in Osmotic and Tensile Expansion Microscopy: A Comparison of MAGNIFY and TExM*

Tejasvin Shrikanth, with Vignesh Venkataramani and Lydia Kisley, Department of Physics, Case Western Reserve University.

- [research_proposal.pdf](research_proposal.pdf) — compiled proposal
- [doc_body.tex](doc_body.tex) — LaTeX source (APS REVTeX 4.2), with [bibfile.bib](bibfile.bib) and [figures/](figures/)
- The full PDF is also on the blog: [Research proposal (full PDF)](../blog/2026-10-30-research-proposal-pdf.md)
- A plain-language version is on the blog: [The research proposal: what the markers are for](../blog/2026-10-30-research-proposal-anisotropy.md)

## Building

The REVTeX class and style files are in `tex/` and `bst/`, and `latexmkrc` points TeX at them:

```bash
cd proposal && latexmk -pdf doc_body.tex
```
