# RootOS

**Root OS** — a lightweight mobile OS for smartphones, built on the Linux kernel and inspired by Android.

**Key feature:** every application runs in its own isolated rootfs environment via `chroot`. The OS includes a permission system implemented through FUSE, along with a custom package manager. The installer uses a custom `.app` package format.

> **Warning:** The OS is in the earliest stage of development.

---

## How to create a `.app` package?

A `.app` package is a tar archive that must contain a `manifest.json` file, along with all necessary application files:
- libraries — in the `/lib` directory
- binaries — in the `/bin` directory
- and so on
For run program - must contain in /bin binary app like a entry.
During installation, the default rootfs and the package contents are merged. The project folder must be structured so that the files end up in the root of the archive upon extraction — not inside an extra nested project folder.

Packaging command using `tar`:
`tar -cvf YourApp.app -C /folder/of/your/project`

Build examples can be found in the `examples` folder.


## How to install a package?

The `appinstaller.py` script is located in the `/src/pm-manager` directory. Currently it supports the `install` and `run` commands.

Usage example:
`./appinstaller.py install YourPackage.app YourDefaultRootfs.tar`


Replace `YourPackage.app` and `YourDefaultRootfs.tar` with your own files.
