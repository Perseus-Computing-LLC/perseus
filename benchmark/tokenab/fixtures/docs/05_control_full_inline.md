@perseus v1.0.8

# Control Document: full inline, no windowing

This control variant uses include directives with no windowing options, so
Perseus inlines each referenced file in full. It keeps the harness honest:
when none of the reduction features are used, the two arms should carry
nearly the same token count and the measured reduction should be near zero
(or negative, since the rendered arm adds framing).

## CLI reference

@include docs/CLI.md

## Contribution rules

@include CONTRIBUTING.md
