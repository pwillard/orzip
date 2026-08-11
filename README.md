# ORZIP

ORZIP is a standalone modern Python tool for the MSTS/Open Rails `SIMISA@F` compressed-binary container used by `.s` shape files.

It replaces the old FFEDITC compression wrapper without using `ffeditc_unicode.exe`, `ffedit.exe`, `.tok`, `.bnf`, or `.hdr` files.

References to S1b and S1t refer to the compressed state from a SIMISA perspective, with B representing BINARY (compressed) and T representing  TEXT (uncompressed) 

Typical workflow:

    orzip.exe validate -r --only-s "C:\MSTS\ROUTES\MyRoute\SHAPES"
    orzip.exe roundtrip -r --only-s "C:\MSTS\ROUTES\MyRoute\SHAPES"
    orzip.exe convert -r --only-s "C:\MSTS\ROUTES\MyRoute\SHAPES"

Important: because convert is now in-place by default, make a backup first if you are converting the original MSTS/Open Rails folders directly.
