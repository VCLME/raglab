# Build the raglab technical report.
#   make          -> raglab-rapport.pdf (tectonic if installed, latexmk otherwise)
#   make clean    -> remove intermediate files

DOC := raglab-rapport

.PHONY: all clean

all: $(DOC).pdf

$(DOC).pdf: $(DOC).tex
	@if command -v tectonic >/dev/null 2>&1; then \
		tectonic $(DOC).tex; \
	else \
		latexmk -pdf -interaction=nonstopmode -halt-on-error $(DOC).tex; \
	fi

clean:
	-latexmk -c $(DOC).tex 2>/dev/null
	rm -f $(DOC).aux $(DOC).log $(DOC).out $(DOC).toc $(DOC).fls $(DOC).fdb_latexmk $(DOC).synctex.gz
