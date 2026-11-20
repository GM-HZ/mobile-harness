# Build variants

`store` is the distribution shape: no signed-exec bypass, no runtime ELF loader,
no native overlay. `self` is the self-built shape (exec shim + `mh-exec` +
default overlay groups). `lab` pins every group for experiments.

`scripts/adaptation/variant_check.py` asserts a built HAP matches a variant:

```sh
python3 scripts/adaptation/variant_check.py --list
python3 scripts/adaptation/variant_check.py --variant store --hap <store-unsigned.hap>
python3 scripts/adaptation/variant_check.py --variant self  --hap <self-unsigned.hap>
```

The same assertions run in G4 after each variant build.
