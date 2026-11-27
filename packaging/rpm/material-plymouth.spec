# Builds from source: the RPM ships the sources (code and the plugin manifest); nothing is rendered or rebuilt when it is installed. Turning the boot splash
# on rebuilds the initramfs and may edit the kernel command line, so it is the person's own step: `material-boot plymouth apply` (or the GUI).
Name:           material-plymouth
Version:        1.1.0
Release:        1%{?dist}
Summary:        Material 3 Expressive boot splash (Plymouth) that continues the Material GRUB theme
License:        MIT
URL:            https://github.com/LucaCraft89/material-plymouth
Source0:        %{url}/archive/v%{version}/%{name}-%{version}.tar.gz
BuildArch:      noarch
Requires:       material-boot-core >= 1.0.0
Requires:       plymouth
Requires:       plymouth-plugin-script
Requires:       plymouth-plugin-label
Requires:       plymouth-scripts
Requires:       dracut
Requires:       python3
Requires:       python3-pillow

%description
A boot splash for Plymouth in the style of the Material GRUB theme: the same colours, the same per-distro look, an animated cookie and shapes, the
Material 3 Expressive wavy loading bar, the disk-password prompt and the shutdown and update messages. It is a part of Material Boot
(`material-boot plymouth ...`) and is managed from material-grub's GUI too. Installing the package does not change how your system boots; apply it yourself.

%prep
%autosetup -n %{name}-%{version}

%install
sh packaging/install-tree.sh . %{buildroot}

%posttrans
/usr/share/material-plymouth/bin/package-hook.sh configure || :

%preun
if [ $1 -eq 0 ]; then /usr/share/material-plymouth/bin/package-hook.sh remove || :; fi

%files
%license LICENSE
%doc README.md
%{_datadir}/material-plymouth
%{_datadir}/material-boot/plugins.d/plymouth.json

%changelog
* Fri Nov 27 2026 LucaCraft89 <noreply@users.noreply.github.com> - 1.1.0-1
- The installer screen asks the loading bar, the motion and the command line (install.questions).

* Mon Nov 23 2026 LucaCraft89 <noreply@users.noreply.github.com> - 1.0.0-1
- First release, level with material-grub (maintainer's decision: the three repositories start at 1.0.0).
