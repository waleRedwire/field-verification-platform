"""
Google Sheets + Google Drive helpers using a Service Account.
"""
from typing import Optional
import io
import pandas as pd
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import gspread

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive"
]


def get_credentials(service_account_file: str) -> Credentials:
    return Credentials.from_service_account_file(
        service_account_file,
        scopes=SCOPES
    )


def load_google_sheet(
    service_account_file: str,
    sheet_url_or_id: str,
    worksheet_name: Optional[str] = None
) -> pd.DataFrame:
    creds = get_credentials(service_account_file)
    client = gspread.authorize(creds)

    if "docs.google.com" in sheet_url_or_id:
        spreadsheet = client.open_by_url(sheet_url_or_id)
    else:
        spreadsheet = client.open_by_key(sheet_url_or_id)

    if worksheet_name:
        worksheet = spreadsheet.worksheet(worksheet_name)
    else:
        worksheet = spreadsheet.sheet1

    data = worksheet.get_all_records()
    return pd.DataFrame(data)


def upload_file_to_drive_folder(
    service_account_file: str,
    folder_id: str,
    file_name: str,
    file_bytes: bytes,
    mime_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
) -> str:
    creds = get_credentials(service_account_file)
    drive_service = build("drive", "v3", credentials=creds)

    file_metadata = {
        "name": file_name,
        "parents": [folder_id]
    }

    media = MediaIoBaseUpload(
        io.BytesIO(file_bytes),
        mimetype=mime_type,
        resumable=True
    )

    uploaded = drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink",
        supportsAllDrives=True
    ).execute()

    return uploaded.get("webViewLink", f"https://drive.google.com/file/d/{uploaded.get('id')}")