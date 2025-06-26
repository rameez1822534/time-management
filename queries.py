import psycopg2
import json
from config import config
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template
from azure.storage.blob import BlobServiceClient
from vault_secrets import get_secret

# Azure Blob Storage
AZURE_CONN_STR = get_secret("AZURECONNSTR")
CONTAINER_NAME = "reportinglayer"

blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONN_STR)

try:
    container_client = blob_service_client.create_container(CONTAINER_NAME)
except Exception:
    container_client = blob_service_client.get_container_client(CONTAINER_NAME)


def query_person():
    try:
        con = psycopg2.connect(**config())
        cursor = con.cursor()

        cursor.execute("SELECT * FROM time_report;")
        rows = cursor.fetchall()

        consultant_list = [r[2] for r in rows]  # Assuming the first column is the consultant name  
        consultant_list = list(set(consultant_list))  # Remove duplicates
        cursor.close()
        con.close()

        return json.dumps(consultant_list)
    except Exception as e:
        return json.dumps({"error": str(e)})



def time_entry(data):
    try:
        con = psycopg2.connect(**config())
        cur = con.cursor()

        # Time calculations
        start = datetime.fromisoformat(data["start_time"])
        end = datetime.fromisoformat(data["end_time"])
        lunch_parts = list(map(int, data["lunch_break"].split(":")))
        lunch = timedelta(hours=lunch_parts[0], minutes=lunch_parts[1])
        worked_time = end - start - lunch
        worked_hours_interval = timedelta(seconds=worked_time.total_seconds())

        # Insert time entry
        cur.execute("""
            INSERT INTO time_report (
                consultant_id, consultant_name, customer_name,
                start_time, end_time, lunch_break
            ) VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            data["consultant_id"],
            data["consultant_name"],
            data["customer_name"],
            start,
            end,
            lunch
        ))

        # Insert or update consultant balance
        cur.execute("""
            INSERT INTO consultant_balances (consultant_name, customer_name, total_hours)
            VALUES (%s, %s, %s)
            ON CONFLICT (consultant_name, customer_name)
            DO UPDATE SET total_hours = consultant_balances.total_hours + EXCLUDED.total_hours
        """, (
            data["consultant_name"],
            data["customer_name"],
            worked_hours_interval
        ))

        con.commit()        
        cur.close()
        con.close()          

        return jsonify({"message": f"{worked_hours_interval} hours logged successfully!"}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 400



def generate_report():
    try:
        conn = psycopg2.connect(**config())
        cur = conn.cursor()

        # --- DAILY HOURS ---
        cur.execute("""
            SELECT DATE(start_time) AS day, consultant_name, customer_name,
                   ROUND(EXTRACT(EPOCH FROM SUM(end_time - start_time - lunch_break)) / 3600, 2) AS hours
            FROM time_report
            GROUP BY day, consultant_name, customer_name
            ORDER BY day, consultant_name;
        """)
        daily = cur.fetchall()

        # --- AVERAGE HOURS PER CONSULTANT ---
        cur.execute("""
            SELECT consultant_name,
                   ROUND(AVG(daily_hours), 2) AS avg_daily
            FROM (
                SELECT consultant_name, DATE(start_time) AS day,
                       EXTRACT(EPOCH FROM SUM(end_time - start_time - lunch_break)) / 3600 AS daily_hours
                FROM time_report
                GROUP BY consultant_name, day
            ) AS sub
            GROUP BY consultant_name
            ORDER BY consultant_name;
        """)
        avg = cur.fetchall()

        # --- WEEKLY TOTALS ---
        cur.execute("""
            SELECT DATE_TRUNC('week', start_time)::date AS week_start,
                   consultant_name,
                   customer_name,
                   ROUND(EXTRACT(EPOCH FROM SUM(end_time - start_time - lunch_break)) / 3600, 2) AS hours
            FROM time_report
            GROUP BY week_start, consultant_name, customer_name
            ORDER BY week_start, consultant_name;
        """)
        weekly = cur.fetchall()

        # --- CUMULATIVE TOTAL BY CUSTOMER ---
        cur.execute("""
            SELECT customer_name,
                   ROUND(EXTRACT(EPOCH FROM SUM(end_time - start_time - lunch_break)) / 3600, 2) AS total
            FROM time_report
            GROUP BY customer_name
            ORDER BY customer_name;
        """)
        cumulative = cur.fetchall()

        # --- FORMAT REPORT ---
        report_lines = []

        # Daily section
        report_lines.append("--- Daily Hours ---")
        report_lines.append("Date       | Consultant   | Customer     | Hours")
        for row in daily:
            report_lines.append(f"{row[0].strftime('%Y-%m-%d')} | {row[1]:<12} | {row[2]:<12} | {row[3]:>5}")

        # Average section
        report_lines.append("\n--- Average per Consultant ---")
        report_lines.append("Consultant   | Avg Daily Hours")
        for row in avg:
            report_lines.append(f"{row[0]:<13} | {row[1]:>5}")

        # Weekly section
        report_lines.append("\n--- Weekly Hours ---")
        report_lines.append("Week Start | Consultant   | Customer     | Hours")
        for row in weekly:
            report_lines.append(f"{row[0].strftime('%Y-%m-%d')} | {row[1]:<12} | {row[2]:<12} | {row[3]:>5}")

        # Cumulative section
        report_lines.append("\n--- Cumulative by Customer ---")
        report_lines.append("Customer     | Total Hours")
        for row in cumulative:
            report_lines.append(f"{row[0]:<13} | {row[1]:>5}")

        # Join all
        report = "\n".join(report_lines)

        # Upload to Azure Blob Storage
        blob_name = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        blob_client = container_client.get_blob_client(blob_name)
        blob_client.upload_blob(report, overwrite=True)

        cur.close()
        conn.close()

        return jsonify({"message": "Report uploaded successfully", "blob_name": blob_name}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500



if __name__ == '__main__':
    query_person()