import os
import platform
import subprocess
import shlex
import pipes
from PySide2 import QtCore, QtGui, QtWidgets
from colorama import Fore

if platform.system() == "Darwin":
    import CoreServices
    import LaunchServices
    import plistlib

elif platform.system() == "Linux":
    import grp
    import getpass
    from xdg.DesktopEntry import DesktopEntry

from .docker_installer import is_docker_ready
from ..settings import Settings


class GuiCommon(object):
    """
    The GuiCommon class is a singleton of shared functionality for the GUI
    """

    def __init__(self, app, global_common):
        # Qt app
        self.app = app

        # Global common singleton
        self.global_common = global_common

        # Preload font
        self.fixed_font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)

        # Preload list of PDF viewers on computer
        self.pdf_viewers = self._find_pdf_viewers()

    def get_window_icon(self):
        if platform.system() == "Windows":
            path = self.global_common.get_resource_path("dangerzone.ico")
        else:
            path = self.global_common.get_resource_path("icon.png")
        return QtGui.QIcon(path)

    def open_pdf_viewer(self, filename):
        if self.global_common.settings.get("open_app") in self.pdf_viewers:
            if platform.system() == "Darwin":
                # Get the PDF reader bundle command
                bundle_identifier = self.pdf_viewers[
                    self.global_common.settings.get("open_app")
                ]
                args = ["open", "-b", bundle_identifier, filename]

                # Run
                args_str = " ".join(pipes.quote(s) for s in args)
                print(Fore.YELLOW + "\u2023 " + Fore.CYAN + args_str)  # ‣
                subprocess.run(args)

            elif platform.system() == "Linux":
                # Get the PDF reader command
                args = shlex.split(
                    self.pdf_viewers[self.global_common.settings.get("open_app")]
                )
                # %f, %F, %u, and %U are filenames or URLS -- so replace with the file to open
                for i in range(len(args)):
                    if (
                        args[i] == "%f"
                        or args[i] == "%F"
                        or args[i] == "%u"
                        or args[i] == "%U"
                    ):
                        args[i] = filename

                # Open as a background process
                args_str = " ".join(pipes.quote(s) for s in args)
                print(Fore.YELLOW + "\u2023 " + Fore.CYAN + args_str)  # ‣
                subprocess.Popen(args)

    def _find_pdf_viewers(self):
        pdf_viewers = {}

        if platform.system() == "Darwin":
            # Get all installed apps that can open PDFs
            bundle_identifiers = LaunchServices.LSCopyAllRoleHandlersForContentType(
                "com.adobe.pdf", CoreServices.kLSRolesAll
            )
            for bundle_identifier in bundle_identifiers:
                # Get the filesystem path of the app
                res = LaunchServices.LSCopyApplicationURLsForBundleIdentifier(
                    bundle_identifier, None
                )
                if res[0] is None:
                    continue
                app_url = res[0][0]
                app_path = str(app_url.path())

                # Load its plist file
                plist_path = os.path.join(app_path, "Contents/Info.plist")

                # Skip if there's not an Info.plist
                if not os.path.exists(plist_path):
                    continue

                with open(plist_path, "rb") as f:
                    plist_data = f.read()

                plist_dict = plistlib.loads(plist_data)

                if (
                    plist_dict.get("CFBundleName")
                    and plist_dict["CFBundleName"] != "Dangerzone"
                ):
                    pdf_viewers[plist_dict["CFBundleName"]] = bundle_identifier

        elif platform.system() == "Linux":
            # Find all .desktop files
            for search_path in [
                "/usr/share/applications",
                "/usr/local/share/applications",
                os.path.expanduser("~/.local/share/applications"),
            ]:
                try:
                    for filename in os.listdir(search_path):
                        full_filename = os.path.join(search_path, filename)
                        if os.path.splitext(filename)[1] == ".desktop":

                            # See which ones can open PDFs
                            desktop_entry = DesktopEntry(full_filename)
                            if (
                                "application/pdf" in desktop_entry.getMimeTypes()
                                and desktop_entry.getName() != "dangerzone"
                            ):
                                pdf_viewers[
                                    desktop_entry.getName()
                                ] = desktop_entry.getExec()

                except FileNotFoundError:
                    pass

        return pdf_viewers

    def ensure_docker_group_preference(self):
        # If the user prefers typing their password
        if self.global_common.settings.get("linux_prefers_typing_password") == True:
            return True

        # Get the docker group
        try:
            groupinfo = grp.getgrnam("docker")
        except:
            # Ignore if group is not found
            return True

        # See if the user is in the group
        username = getpass.getuser()
        if username not in groupinfo.gr_mem:
            # User is not in the docker group, ask if they prefer typing their password
            message = "<b>Dangerzone requires Docker</b><br><br>In order to use Docker, your user must be in the 'docker' group or you'll need to type your password each time you run dangerzone.<br><br><b>Adding your user to the 'docker' group is more convenient but less secure</b>, and will require just typing your password once. Which do you prefer?"
            return_code = Alert(
                self,
                self.global_common,
                message,
                ok_text="I'll type my password each time",
                extra_button_text="Add my user to the 'docker' group",
            ).launch()
            if return_code == QtWidgets.QDialog.Accepted:
                # Prefers typing password
                self.global_common.settings.set("linux_prefers_typing_password", True)
                self.global_common.settings.save()
                return True
            elif return_code == 2:
                # Prefers being in the docker group
                self.global_common.settings.set("linux_prefers_typing_password", False)
                self.global_common.settings.save()

                # Add user to the docker group
                p = subprocess.run(
                    [
                        "/usr/bin/pkexec",
                        "/usr/sbin/usermod",
                        "-a",
                        "-G",
                        "docker",
                        username,
                    ]
                )
                if p.returncode == 0:
                    message = "Great! Now you must log out of your computer and log back in, and then you can use Dangerzone."
                    Alert(self, self.global_common, message).launch()
                else:
                    message = "Failed to add your user to the 'docker' group, quitting."
                    Alert(self, self.global_common, message).launch()

                return False
            else:
                # Cancel
                return False

        return True

    def ensure_docker_service_is_started(self):
        if not is_docker_ready(self.global_common):
            message = "<b>Dangerzone requires Docker</b><br><br>Docker should be installed, but it looks like it's not running in the background.<br><br>Click Ok to try starting the docker service. You will have to type your login password."
            if (
                Alert(self, self.global_common, message).launch()
                == QtWidgets.QDialog.Accepted
            ):
                p = subprocess.run(
                    [
                        "/usr/bin/pkexec",
                        self.global_common.get_resource_path(
                            "enable_docker_service.sh"
                        ),
                    ]
                )
                if p.returncode == 0:
                    # Make sure docker is now ready
                    if is_docker_ready(self.global_common):
                        return True
                    else:
                        message = "Restarting docker appeared to work, but the service still isn't responding, quitting."
                        Alert(self, self.global_common, message).launch()
                else:
                    message = "Failed to start the docker service, quitting."
                    Alert(self, self.global_common, message).launch()

            return False

        return True


class Alert(QtWidgets.QDialog):
    def __init__(
        self, gui_common, global_common, message, ok_text="Ok", extra_button_text=None
    ):
        super(Alert, self).__init__()
        self.global_common = global_common
        self.gui_common = gui_common

        self.setWindowTitle("dangerzone")
        self.setWindowIcon(self.gui_common.get_window_icon())
        self.setModal(True)

        flags = (
            QtCore.Qt.CustomizeWindowHint
            | QtCore.Qt.WindowTitleHint
            | QtCore.Qt.WindowSystemMenuHint
            | QtCore.Qt.WindowCloseButtonHint
            | QtCore.Qt.WindowStaysOnTopHint
        )
        self.setWindowFlags(flags)

        logo = QtWidgets.QLabel()
        logo.setPixmap(
            QtGui.QPixmap.fromImage(
                QtGui.QImage(self.global_common.get_resource_path("icon.png"))
            )
        )

        label = QtWidgets.QLabel()
        label.setText(message)
        label.setWordWrap(True)

        message_layout = QtWidgets.QHBoxLayout()
        message_layout.addWidget(logo)
        message_layout.addSpacing(10)
        message_layout.addWidget(label, stretch=1)

        ok_button = QtWidgets.QPushButton(ok_text)
        ok_button.clicked.connect(self.clicked_ok)
        if extra_button_text:
            extra_button = QtWidgets.QPushButton(extra_button_text)
            extra_button.clicked.connect(self.clicked_extra)
        cancel_button = QtWidgets.QPushButton("Cancel")
        cancel_button.clicked.connect(self.clicked_cancel)

        buttons_layout = QtWidgets.QHBoxLayout()
        buttons_layout.addStretch()
        buttons_layout.addWidget(ok_button)
        if extra_button_text:
            buttons_layout.addWidget(extra_button)
        buttons_layout.addWidget(cancel_button)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(message_layout)
        layout.addSpacing(10)
        layout.addLayout(buttons_layout)
        self.setLayout(layout)

    def clicked_ok(self):
        self.done(QtWidgets.QDialog.Accepted)

    def clicked_extra(self):
        self.done(2)

    def clicked_cancel(self):
        self.done(QtWidgets.QDialog.Rejected)

    def launch(self):
        return self.exec_()
