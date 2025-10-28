import json  
import os  
import time  
from datetime import datetime  
import requests  
from dotenv import load_dotenv  
  
# ---------------------------------------------------------------------  
# LOAD ENVIRONMENT CONFIG  
# ---------------------------------------------------------------------  
load_dotenv()  
  
ENDPOINT = os.getenv("ENDPOINT", "https://<YOUR-ENDPOINT>.cognitiveservices.azure.com/")  
API_KEY = os.getenv("API_KEY", "<YOUR-API-KEY>")  
API_VERSION = os.getenv("API_VERSION", "2025-05-01-preview")  
ANALYZER_ID = os.getenv("ANALYZER_ID", "myAnalyzer")  
MODE = os.getenv("MODE", "standard")  # "standard" or "pro"  
  
INPUT_FOLDER = os.getenv("INPUT_FOLDER", "input")  
TEST_DATA_FOLDER = os.getenv("TEST_DATA_FOLDER", "test_data")  
OUTPUT_FOLDER = os.getenv("OUTPUT_FOLDER", "output")  
SCHEMA_FILE = os.getenv("SCHEMA_FILE", "schema.json")
  
  
# ---------------------------------------------------------------------  
# VALIDATION & SETUP  
# ---------------------------------------------------------------------  
def validate_environment():  
    required_vars = ["ENDPOINT", "API_KEY"]  
    missing = [v for v in required_vars if not os.getenv(v) or os.getenv(v).startswith("<YOUR-")]  
    if missing:  
        print(f"❌ Missing environment variables: {', '.join(missing)}. Update your .env file.")  
        exit(1)  
  
    os.makedirs(INPUT_FOLDER, exist_ok=True)  
    os.makedirs(TEST_DATA_FOLDER, exist_ok=True)  
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)  
    print("✅ Environment validated.")  
  
  
def get_input_files():  
    if not os.path.exists(INPUT_FOLDER):  
        os.makedirs(INPUT_FOLDER, exist_ok=True)  
        return []  
    input_files = [f for f in os.listdir(INPUT_FOLDER)  
                   if f.lower().endswith((".pdf", ".docx", ".txt", ".png", ".jpg", ".jpeg", ".mp4", ".wav"))]  
    input_paths = [os.path.join(INPUT_FOLDER, f) for f in input_files]  
    print(f"📁 Found {len(input_files)} input files: {input_files}")  
    return input_paths   
  
  
def get_test_data_file(file_path):  
    base = os.path.splitext(os.path.basename(file_path))[0]  
    test_file = os.path.join(TEST_DATA_FOLDER, f"{base}.json")  
    return test_file if os.path.exists(test_file) else None  
  
  
# ---------------------------------------------------------------------  
# UTILS  
# ---------------------------------------------------------------------  
def load_json_file(path):  
    if not os.path.exists(path):  
        raise FileNotFoundError(f"File not found: {path}")  
    with open(path, "r", encoding="utf-8") as f:  
        return json.load(f)  


def create_evaluation_run_folder():
    """Create an incrementally numbered subfolder for this evaluation run."""
    # Find the next available run number
    run_number = 1
    while True:
        run_folder = os.path.join(OUTPUT_FOLDER, f"run_{run_number:03d}")
        if not os.path.exists(run_folder):
            break
        run_number += 1
    
    os.makedirs(run_folder, exist_ok=True)
    print(f"📁 Created evaluation run folder: {run_folder}")
    return run_folder, f"{run_number:03d}"
  
  
def save_json(data, run_folder, filename):  
    """Save JSON data to the evaluation run folder with specified filename."""
    file_path = os.path.join(run_folder, filename)  
    with open(file_path, "w", encoding="utf-8") as f:  
        json.dump(data, f, indent=2)  
    print(f"💾 Saved: {file_path}")  
    return file_path  

def extract_actual_value(details):  
    if not isinstance(details, dict):  
        # Defensive: if details is already a primitive, just return it  
        return details  
    typ = details.get("type")  
    if typ == "string":  
        return details.get("valueString")  
    elif typ == "number":  
        return details.get("valueNumber")  
    elif typ == "date":  
        return details.get("valueDate")  
    elif typ == "boolean":  
        return details.get("valueBoolean")  
    elif typ == "integer":  
        return details.get("valueInteger")  
    elif typ == "time":  
        v = details.get("valueTime")  
        if v and v.endswith(":00"):  
            return v[:-3]  
        return v  
    elif typ == "array":  
        arr = details.get("valueArray", [])  
        extracted = []  
        for item in arr:  
            extracted.append(extract_actual_value(item))  
        return extracted  
    elif typ == "object":  
        obj = details.get("valueObject", {})  
        return {k: extract_actual_value(v) for k, v in obj.items()}  
    else:  
        return None  

# ---------------------------------------------------------------------  
# PRICING CALCULATIONS  
# ---------------------------------------------------------------------  
def calculate_document_cost(usage_data, mode="standard"):
    """Calculate the cost for a single document based on usage data and mode."""
    costs = {
        "content_extraction": 0,
        "field_extraction": 0,
        "contextualization": 0,
        "total": 0
    }
    
    # Content Extraction (Document): $5 per 1,000 pages
    document_pages = usage_data.get("documentPages", 0)
    costs["content_extraction"] = (document_pages / 1000) * 5.0
    
    # Field Extraction tokens
    tokens = usage_data.get("tokens", {})
    input_tokens = tokens.get("input", 0)
    output_tokens = tokens.get("output", 0)
    contextualization_tokens = tokens.get("contextualization", 0)
    
    # Field Extraction pricing depends on mode
    if mode.lower() == "pro":
        # Pro Field Extraction: Input $1.21/1M tokens, Output $4.84/1M tokens
        costs["field_extraction"] = (input_tokens / 1000000) * 1.21 + (output_tokens / 1000000) * 4.84
        # Pro Contextualization: $1.50/1M tokens
        costs["contextualization"] = (contextualization_tokens / 1000000) * 1.50
    else:
        # Standard Field Extraction: Input $2.75/1M tokens, Output $11/1M tokens
        costs["field_extraction"] = (input_tokens / 1000000) * 2.75 + (output_tokens / 1000000) * 11.0
        # Standard Contextualization: $1/1M tokens
        costs["contextualization"] = (contextualization_tokens / 1000000) * 1.0
    
    costs["total"] = costs["content_extraction"] + costs["field_extraction"] + costs["contextualization"]
    
    return costs


def aggregate_costs(document_costs):
    """Aggregate costs across all documents."""
    totals = {
        "content_extraction": 0,
        "field_extraction": 0,
        "contextualization": 0,
        "total": 0
    }
    
    for cost in document_costs:
        for key in totals:
            totals[key] += cost[key]
    
    return totals


def format_currency(amount):
    """Format amount as USD currency."""
    return f"${amount:.2f}"


# ---------------------------------------------------------------------  
# ANALYZER MANAGEMENT  
# ---------------------------------------------------------------------  
def delete_analyzer():  
    url = f"{ENDPOINT}/contentunderstanding/analyzers/{ANALYZER_ID}?api-version={API_VERSION}"  
    headers = {"Ocp-Apim-Subscription-Key": API_KEY}  
    print(f"🗑️ Deleting analyzer '{ANALYZER_ID}'...")  
    resp = requests.delete(url, headers=headers)  
    if resp.status_code == 204:  
        print("✅ Analyzer deleted.")  
    elif resp.status_code == 404:  
        print("ℹ️ Analyzer not found.")  
    else:  
        print(f"⚠️ Delete failed: {resp.status_code} {resp.text}")  
  
  
def create_analyzer():  
    """Create analyzer using only fieldSchema from JSON file."""  
    schema_data = load_json_file(SCHEMA_FILE)  
    
    # Extract fieldSchema from the loaded data
    # Handle both direct fieldSchema and nested structure
    if "fieldSchema" in schema_data:
        field_schema = schema_data["fieldSchema"]
    else:
        # Assume the entire file is the field schema
        field_schema = schema_data
  
    schema = {  
        "description": f"Auto-created analyzer using field schema from {SCHEMA_FILE}",  
        "baseAnalyzerId": "prebuilt-documentAnalyzer",  
        "mode": MODE,  
        "processingLocation": "global" if MODE == "pro" else "geography",  
        "config": {"returnDetails": True},  
        "fieldSchema": field_schema  
    }  
  
    url = f"{ENDPOINT}/contentunderstanding/analyzers/{ANALYZER_ID}?api-version={API_VERSION}"  
    headers = {  
        "Ocp-Apim-Subscription-Key": API_KEY,  
        "Content-Type": "application/json"  
    }  
  
    print(f"🚀 Creating analyzer '{ANALYZER_ID}' in {MODE} mode...")  
    resp = requests.put(url, headers=headers, json=schema)  
    print(f"Status: {resp.status_code}")  
    if resp.status_code not in [200, 201]:  
        raise Exception(f"❌ Analyzer creation failed: {resp.text}")  
    print("✅ Analyzer created successfully.")  
    return schema  
  
  
# ---------------------------------------------------------------------  
# ANALYSIS  
# ---------------------------------------------------------------------  
def analyze_file_binary(file_path):  
    url = f"{ENDPOINT}/contentunderstanding/analyzers/{ANALYZER_ID}:analyze?_overload=analyzeBinary&api-version={API_VERSION}"  
    headers = {"Ocp-Apim-Subscription-Key": API_KEY, "Content-Type": "application/octet-stream"}  
  
    print(f"📤 Uploading {file_path}...")  
    with open(file_path, "rb") as f:  
        data = f.read()  
    resp = requests.post(url, headers=headers, data=data)  
    if resp.status_code != 202:  
        raise Exception(f"❌ Analyze failed: {resp.status_code} {resp.text}")  
    op_loc = resp.headers.get("Operation-Location")  
    print(f"Analysis started. Operation: {op_loc}")  
    return op_loc  
  
  
def poll_result(op_loc):  
    headers = {"Ocp-Apim-Subscription-Key": API_KEY}  
    while True:  
        resp = requests.get(op_loc, headers=headers)  
        data = resp.json()  
        status = data.get("status")  
        if status == "Succeeded":  
            print("✅ Analysis complete.")  
            return data  
        elif status == "Failed":  
            raise Exception("❌ Analysis failed.")  
        print("⏳ Waiting...")  
        time.sleep(3)  
  
  
# ---------------------------------------------------------------------  
# EVALUATION  
# ---------------------------------------------------------------------  
def compare_results_to_testdata(result, testdata):  
    extracted_fields = result["result"]["contents"][0].get("fields", {})  
    success, total = 0, 0  
    field_scores = {}  
    for field, details in extracted_fields.items():  
        expected = testdata.get(field)  
        actual = extract_actual_value(details)
        total += 1  
        if str(expected).strip().lower() == str(actual).strip().lower():  
            success += 1  
            field_scores[field] = {"status": "✅", "expected": expected, "actual": actual}  
        else:  
            field_scores[field] = {"status": "❌", "expected": expected, "actual": actual}  
    accuracy = round((success / total) * 100, 2) if total else 0  
    return accuracy, field_scores  
  
  
def aggregate_field_performance(results):  
    agg = {}  
    for item in results:  
        for field, detail in item["fields"].items():  
            agg.setdefault(field, {"passes": 0, "fails": 0})  
            if detail["status"] == "✅":  
                agg[field]["passes"] += 1  
            else:  
                agg[field]["fails"] += 1  
    print("\n📊 Aggregate Field Performance:")  
    for field, data in agg.items():  
        total = data["passes"] + data["fails"]  
        accuracy = round((data["passes"] / total) * 100, 2) if total else 0  
        print(f"  {field}: {accuracy}% ({data['passes']} pass, {data['fails']} fail)")  
    return agg  


def generate_evaluation_report(run_folder, run_number, results, field_performance, analyzer_config, all_costs):
    """Generate both JSON and markdown reports for the evaluation run."""
    report_path_md = os.path.join(run_folder, "evaluation_report.md")
    report_path_json = os.path.join(run_folder, "evaluation_report.json")
    
    # Calculate overall statistics
    total_docs = len(results) if results else len(all_costs)
    total_fields_tested = sum(len(item["fields"]) for item in results) if results else 0
    total_field_passes = sum(1 for item in results for field, detail in item["fields"].items() if detail["status"] == "✅") if results else 0
    overall_accuracy = round((total_field_passes / total_fields_tested) * 100, 2) if total_fields_tested > 0 else 0
    
    # Calculate aggregate costs
    aggregate_cost = aggregate_costs([cost_data["costs"] for cost_data in all_costs]) if all_costs else {
        "content_extraction": 0, "field_extraction": 0, "contextualization": 0, "total": 0
    }
    
    # Create comprehensive JSON report structure
    json_report = {
        "metadata": {
            "run_id": f"run_{run_number}",
            "run_number": int(run_number),
            "timestamp": datetime.now().strftime('%Y%m%d_%H%M%S'),
            "date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "analyzer_id": ANALYZER_ID,
            "mode": MODE,
            "schema_file": SCHEMA_FILE
        },
        "summary": {
            "documents_analyzed": total_docs,
            "total_fields_tested": total_fields_tested,
            "overall_accuracy": overall_accuracy,
            "field_passes": total_field_passes,
            "field_failures": total_fields_tested - total_field_passes
        },
        "costs": {
            "aggregate": aggregate_cost,
            "per_document": all_costs,
            "mode": MODE
        },
        "results": {
            "document_level": results,
            "field_performance": field_performance
        },
        "analyzer_config": analyzer_config
    }
    
    # Save JSON report
    with open(report_path_json, "w", encoding="utf-8") as f:
        json.dump(json_report, f, indent=2, ensure_ascii=False)
    print(f"📊 Generated JSON report: {report_path_json}")
    
    # Generate markdown content
    content = f"""# Document Analyzer Evaluation Report

**Evaluation Run ID:** run_{run_number}  
**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  
**Analyzer ID:** {ANALYZER_ID}  
**Mode:** {MODE}  
**Schema:** {SCHEMA_FILE}  

## Summary

- **Documents Analyzed:** {total_docs}
- **Total Fields Tested:** {total_fields_tested}
- **Overall Accuracy:** {overall_accuracy}%
- **Field Passes:** {total_field_passes}
- **Field Failures:** {total_fields_tested - total_field_passes}

## Cost Analysis

**Total Cost:** {format_currency(aggregate_cost['total'])}

| Cost Component | Amount | Percentage |
|----------------|--------|------------|
| Content Extraction | {format_currency(aggregate_cost['content_extraction'])} | {(aggregate_cost['content_extraction'] / aggregate_cost['total'] * 100) if aggregate_cost['total'] > 0 else 0:.1f}% |
| Field Extraction | {format_currency(aggregate_cost['field_extraction'])} | {(aggregate_cost['field_extraction'] / aggregate_cost['total'] * 100) if aggregate_cost['total'] > 0 else 0:.1f}% |
| Contextualization | {format_currency(aggregate_cost['contextualization'])} | {(aggregate_cost['contextualization'] / aggregate_cost['total'] * 100) if aggregate_cost['total'] > 0 else 0:.1f}% |

### Per-Document Cost Breakdown

| Document | Pages | Input Tokens | Output Tokens | Context Tokens | Cost |
|----------|-------|--------------|---------------|----------------|------|
"""
    
    # Add per-document cost breakdown
    for cost_data in all_costs:
        doc_name = cost_data["document"]
        usage = cost_data["usage"]
        cost = cost_data["costs"]
        tokens = usage.get("tokens", {})
        
        content += f"| {doc_name} | {usage.get('documentPages', 0)} | {tokens.get('input', 0):,} | {tokens.get('output', 0):,} | {tokens.get('contextualization', 0):,} | {format_currency(cost['total'])} |\n"
    
    # Add pricing information
    content += f"""

### Pricing Details ({MODE.title()} Mode)

**Content Extraction:** $5.00 per 1,000 pages  
**Field Extraction:**"""
    
    if MODE.lower() == "pro":
        content += """
- Input tokens: $1.21 per 1M tokens
- Output tokens: $4.84 per 1M tokens

**Contextualization:** $1.50 per 1M tokens"""
    else:
        content += """
- Input tokens: $2.75 per 1M tokens  
- Output tokens: $11.00 per 1M tokens

**Contextualization:** $1.00 per 1M tokens"""

    # Only add accuracy sections if we have evaluation results
    if results:
        content += "\n## Document-Level Results\n\n| Document | Fields Tested | Accuracy | Pass | Fail |\n|----------|---------------|----------|------|------|\n"
        
        # Add document-level results
        for item in results:
            doc_name = item["doc"]
            fields_count = len(item["fields"])
            doc_passes = sum(1 for detail in item["fields"].values() if detail["status"] == "✅")
            doc_accuracy = round((doc_passes / fields_count) * 100, 2) if fields_count > 0 else 0
            doc_fails = fields_count - doc_passes
            content += f"| {doc_name} | {fields_count} | {doc_accuracy}% | {doc_passes} | {doc_fails} |\n"
        
        # Add field-level performance
        content += "\n## Field-Level Performance\n\n| Field | Total Tests | Accuracy | Passes | Failures |\n|-------|-------------|----------|--------|---------|\n"
        
        for field, data in field_performance.items():
            total = data["passes"] + data["fails"]
            accuracy = round((data["passes"] / total) * 100, 2) if total > 0 else 0
            content += f"| {field} | {total} | {accuracy}% | {data['passes']} | {data['fails']} |\n"
        
        # Add detailed field results per document
        content += "\n## Detailed Results by Document\n\n"
        
        for item in results:
            content += f"### {item['doc']}\n\n| Field | Expected | Actual | Status |\n|-------|----------|--------|--------|\n"
            for field, detail in item["fields"].items():
                status_icon = "✅" if detail["status"] == "✅" else "❌"
                content += f"| {field} | {detail['expected']} | {detail['actual']} | {status_icon} |\n"
            content += "\n"
    
    # Add analyzer configuration section
    content += f"""
## Analyzer Configuration

```json
{json.dumps(analyzer_config, indent=2)}
```

## Files Generated

This evaluation run generated the following files:

- `evaluation_report.md` - This comprehensive markdown report
- `evaluation_report.json` - Machine-readable JSON report for tooling/viewers
"""
    
    # List all JSON files in the run folder
    for cost_data in all_costs:
        base_name = os.path.splitext(cost_data["document"])[0]
        content += f"- `{base_name}.json` - Analysis results for {cost_data['document']}\n"
    
    # Save the report
    with open(report_path_md, "w", encoding="utf-8") as f:
        f.write(content)
    
    print(f"📊 Generated markdown report: {report_path_md}")
    return report_path_json, report_path_md  
  
  
# ---------------------------------------------------------------------  
# MAIN WORKFLOW  
# ---------------------------------------------------------------------  
if __name__ == "__main__":  
    print("\n🔧 Initialising Azure CU Document Analyzer Evaluator")  
    validate_environment()  
    delete_analyzer()  
    analyzer_config = create_analyzer()  
    
    # Create evaluation run folder
    run_folder, run_number = create_evaluation_run_folder()
  
    input_files = get_input_files()  
    if not input_files:  
        print(f"❌ No input files found in '{INPUT_FOLDER}'. Exiting.")  
        exit(0)
  
    all_results = []  
    all_costs = []  # Track costs for each document
    for file_path in input_files:  
        print(f"\n📄 Processing: {os.path.basename(file_path)}")  
        op_loc = analyze_file_binary(file_path)  
        result = poll_result(op_loc)  
        
        # Calculate costs from usage data
        usage_data = result.get("usage", {})
        document_cost = calculate_document_cost(usage_data, MODE)
        all_costs.append({
            "document": os.path.basename(file_path),
            "usage": usage_data,
            "costs": document_cost
        })
        print(f"💰 Cost: {format_currency(document_cost['total'])} (Pages: {usage_data.get('documentPages', 0)}, Tokens: {sum(usage_data.get('tokens', {}).values())})")
        
        # Save with matching filename (no timestamp prefix)
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        result_filename = f"{base_name}.json"
        save_json(result, run_folder, result_filename)
  
        test_file = get_test_data_file(file_path)  
        if test_file:  
            test_data = load_json_file(test_file)  
            accuracy, field_scores = compare_results_to_testdata(result, test_data)  
            print(f"📊 Accuracy: {accuracy}%")  
            for field, detail in field_scores.items():  
                print(f"  {field}: {detail['status']} (expected '{detail['expected']}' vs actual '{detail['actual']}')")  
            all_results.append({"doc": os.path.basename(file_path), "fields": field_scores})  
        else:  
            print(f"ℹ️ No test data found for {os.path.basename(file_path)}")  
  
    if all_results:  
        field_performance = aggregate_field_performance(all_results)
        # Calculate aggregate costs
        aggregate_cost = aggregate_costs([cost_data["costs"] for cost_data in all_costs])
        print(f"\n💰 Total Cost: {format_currency(aggregate_cost['total'])}")
        print(f"   Content Extraction: {format_currency(aggregate_cost['content_extraction'])}")
        print(f"   Field Extraction: {format_currency(aggregate_cost['field_extraction'])}")
        print(f"   Contextualization: {format_currency(aggregate_cost['contextualization'])}")
        
        # Generate comprehensive evaluation report
        json_report_path, md_report_path = generate_evaluation_report(run_folder, run_number, all_results, field_performance, analyzer_config, all_costs)
    else:
        if all_costs:
            # Still show costs even if no evaluation data
            aggregate_cost = aggregate_costs([cost_data["costs"] for cost_data in all_costs])
            print(f"\n💰 Total Cost: {format_currency(aggregate_cost['total'])}")
            json_report_path, md_report_path = generate_evaluation_report(run_folder, run_number, [], {}, analyzer_config, all_costs)
        else:
            print("ℹ️ No test data available for evaluation - skipping report generation")
  
    print(f"\n✅ Evaluation completed. Results saved to: {run_folder}")
    print("✅ Done.")  