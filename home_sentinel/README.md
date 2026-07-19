# Home Sentinel

Home Sentinel is a Raspberry Pi-based edge vision app for:

- live camera view
- manual capture and analysis
- baseline motion monitoring
- object detection and annotation
- stored event images and clips
- network and compute status
- Arducam exposure control and auto-tuning

## Run

The app is designed to run on the Pi in:

`/home/tariye/camera_project`

Start it with:

```bash
export HOMESENTINEL_BASE_DIR=/home/tariye/camera_project
python3 app.py
```

## Dependencies

- `flask`
- `opencv-python`
- `numpy`
- `Pillow`
- `fswebcam`
- `ffmpeg`
- `v4l2-ctl`

## Camera devices

The app expects:

- Arducam: `/dev/v4l/by-id/usb-Arducam_Technology_Co.__Ltd._USB_Camera_SN0001-video-index0`
- Logitech: `/dev/v4l/by-id/usb-046d_C922_Pro_Stream_Webcam_506AEDCF-video-index0`

Override those paths with environment variables if needed:

- `HOMESENTINEL_ARDUCAM_DEVICE`
- `HOMESENTINEL_LOGITECH_DEVICE`
- `HOMESENTINEL_DEFAULT_CAMERA`

## Notes

- Runtime data is intentionally ignored by git.
- The app uses inline HTML and stores events in SQLite.
- The live view includes camera presets and Arducam auto-exposure assist.
