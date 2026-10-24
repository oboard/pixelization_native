# Pixel annotation CLI

Repository-local Node package for palette-index annotation, reusable profiles,
review submission, previews and PNG export. Requires Node 24+ and Python for
recipe commands. The server, palette and Python recipes are resolved relative
to this repository, independently of the current working directory.

## Install and run

```sh
pnpm --dir packages/pixel-annotate install
pnpm --dir packages/pixel-annotate start -- help
node packages/pixel-annotate/pixel_annotate.ts help
pnpm --dir packages/pixel-annotate typecheck
```

Node runs the TypeScript source directly; no build step or tsx loader is needed.
TypeScript 7+ checks the source using erasable syntax only. Dependencies belong
to this package, including pngjs (no dependency on webui/node_modules).

```sh
node packages/pixel-annotate/pixel_annotate.ts list --status unqualified
node packages/pixel-annotate/pixel_annotate.ts recipe-preview 184 --sizes 24,52,78,104
node packages/pixel-annotate/pixel_annotate.ts recipe-apply 184 --sizes 24,52,78,104
```

All authoritative sample and profile writes use the annotation server API.
Set PIXEL_ANNOTATION_SERVER and optionally PIXEL_ANNOTATION_TOKEN for another
server. Existing reviewed samples are protected by default. Profile JSON files
are versioned; dependencies and local datasets are ignored.

## Repair a broken silhouette

`profile-outline ID --size 52 --color 198` outlines the largest four-connected
opaque component in an existing profile grid. Separate decorations (such as
lightning) are left alone. It changes the draft profile only; inspect with
`recipe-preview` before submitting. Check that decorations are not connected
to the subject, since connected pixels belong to the same component.

## Repair edge colors selectively

`profile-edge-map ID --size 78 --map 184:69,82:69` recolors only mapped
pixels touching transparency or the canvas boundary in four directions.
It uses a snapshot, so changes do not spread inward. All components are
included; interior highlights remain unchanged. This updates the draft only;
inspect `recipe-preview` before `recipe-apply`.
