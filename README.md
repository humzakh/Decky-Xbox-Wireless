# Xbox Wireless for Decky

Decky plugin for Xbox controllers and headsets using the [xone](https://github.com/dlundqvist/xone) driver on SteamOS. Integrates the Xbox Wireless Adapter into SteamOS for a near-native experience.

## Install

```sh
pnpm install
./deploy.sh zip           # then Decky > Developer > Install Plugin from ZIP
./deploy.sh deck@<host>   # or deploy over SSH
```

## Notes

- xone only reports battery as Low, Medium, High or Full.
- If the adapter stops working after reinstalling the driver, unplug it and plug it back in.

## Development

```sh
pnpm run typecheck
pnpm run build
pnpm test
```
