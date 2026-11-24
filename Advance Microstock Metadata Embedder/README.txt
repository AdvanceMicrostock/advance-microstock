================================================================
                      METADATA EMBEDDER
                    Easy Setup Guide (Windows)
================================================================

WHAT IT DOES
  Puts Title, Description and Keywords from your CSV file
  inside your files. You only choose the files and the CSV.

WORKS WITH
  Images  : JPG, JPEG, PNG, WEBP
  Vectors : EPS, AI, SVG
  Videos  : MP4, MOV, WebM

CSV FORMAT (first row = header)
  Filename, Title, Description, Keywords


================================================================
 QUICK SUMMARY
================================================================
  1. Install Python        (installer is already in this folder)
  2. Add ExifTool          (download 1 zip)
  3. Add FFmpeg            (only if you use WebM)
  4. Make the shortcut     (double-click 1 file)
  5. Open the app and embed


================================================================
 STEP 1 - INSTALL PYTHON  (one time only)
================================================================
  Good news: Python is already included in this folder.

  File name:  python-3.13.9-amd64.exe
  Use this one. It is tested and works with this app.

  How to install
    1. Double-click python-3.13.9-amd64.exe
    2. At the bottom of the first screen, tick
          [x] Add python.exe to PATH
       (Very important. Without it the app will not open.)
    3. Click "Install Now"
    4. Click "Yes" if Windows asks, then click "Close"

  Check it worked
    Press the Windows key, type  cmd , press Enter, then type
        python --version
    If you see a version number, Python is ready.

  Want another Python version? You can download one here:
    https://www.python.org/downloads/windows/
  Use Python 3.10 or newer. Always tick "Add python.exe to PATH".
  If Python is already installed on your PC, skip this step.


================================================================
 STEP 2 - ADD EXIFTOOL
================================================================
  Needed for: JPG, PNG, WEBP, AI, MP4, MOV
  (EPS and SVG do not need it.)

  1. Open:  https://exiftool.org/
  2. Click "Windows Executable" to download the zip.
  3. Open the zip file.
  4. Rename  exiftool(-k).exe   to   exiftool.exe
  5. Put these 2 things in the app folder:
        exiftool.exe
        exiftool_files        (folder - do not delete it)


================================================================
 STEP 3 - ADD FFMPEG  (only for WebM, optional)
================================================================
  1. Download (direct link):
       https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip
     Other builds:
       https://www.gyan.dev/ffmpeg/builds/
  2. Open the zip, then open the "bin" folder.
  3. Copy only  ffmpeg.exe  into the app folder.
  4. Skip this step if you do not use WebM files.


================================================================
 STEP 4 - CHECK THE APP FOLDER
================================================================
  Keep everything together in ONE folder, for example:
      Desktop\Metadata Embedder

  The folder should have:
      Metadata_Embedder.py
      Metadata_Embedder.exe        (launcher, if you have it)
      Start_App.bat                (use this if there is no .exe)
      Create_Desktop_Shortcut.bat
      exiftool.exe
      exiftool_files               (folder)
      ffmpeg.exe                   (only for WebM)

  Do not move the folder later. If you move it,
  run Step 5 again.


================================================================
 STEP 5 - MAKE THE SHORTCUT
================================================================
  Double-click:  Create_Desktop_Shortcut.bat

  A "Metadata Embedder" shortcut appears on your Desktop
  and in the Start Menu.

  Want a Start Menu tile?
  Search "Metadata Embedder" in Start, right-click it,
  then click "Pin to Start".


================================================================
 STEP 6 - USE THE APP
================================================================
  1. Open the "Metadata Embedder" shortcut.
  2. Add your files and your CSV:
       - drag & drop them, or
       - click "Browse Files + CSV" or "Select Folder"
  3. Keep "Back up originals" ticked.
     Your original files are saved in _backup_originals.
  4. Click "Embed Metadata".
     You can Pause or Stop while it is running.

  TIP: Try 2-3 copies of your files first.


================================================================
 PROBLEMS?
================================================================
  The app does not open
    -> Check that Python is installed (see Step 1).
    -> Run Start_App_Debug.bat (if you have it) to see the error.

  Files shown as [MISSING]
    -> The Filename in the CSV must match the real file name
       exactly, with the extension. Example: photo1.jpg

  error_log.txt or crash_log.txt appeared
    -> Something failed. Open the file to read the details.

  The shortcut stopped working
    -> You moved the folder. Run Create_Desktop_Shortcut.bat again.

================================================================
