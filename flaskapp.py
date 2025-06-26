from flask import Flask, request, jsonify, render_template
from datetime import datetime, timedelta
from azure.storage.blob import BlobServiceClient
import psycopg2
from config import config
from vault_secrets import get_secret
from queries import query_person , time_entry ,generate_report


app = Flask(__name__)

# Azure Blob Storage
AZURE_CONN_STR = get_secret("AZURECONNSTR")
CONTAINER_NAME = "reportinglayer"

blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONN_STR)

try:
    container_client = blob_service_client.create_container(CONTAINER_NAME)
except Exception:
    container_client = blob_service_client.get_container_client(CONTAINER_NAME)

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route('/consultants', methods=['GET'])
def get_all_person():
    try:
        return query_person()
    except Exception as e:
        return {"error": str(e)}, 500



@app.route('/logTime', methods=['POST'])
def log_time():
    data = request.get_json()
    try:
        return time_entry(data)         
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/report', methods=['GET'])
def report():
    try:
        return generate_report()
    except Exception as e:
        return jsonify({"error": str(e)}), 500





if __name__ == '__main__':
    app.run(debug=True)
