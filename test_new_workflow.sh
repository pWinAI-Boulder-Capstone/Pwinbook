#!/bin/bash

# Test script for new multi-agent podcast workflow
# This replaces the old podcast_creator with the new Director→Writer→Reviewer→Compliance system

set -e

API_URL="http://localhost:8001/api"

echo "🚀 Testing New Multi-Agent Podcast Workflow"
echo "============================================"
echo ""

# Step 1: Create speaker profile if it doesn't exist
echo "📝 Creating speaker profile..."
SPEAKER_RESPONSE=$(curl -s -X POST "$API_URL/speaker-profiles" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ai_ethics_hosts",
    "speakers": [
      {
        "name": "Dr. Sarah Chen",
        "role": "AI Ethics Researcher",
        "personality": "Thoughtful and analytical",
        "background": "PhD in AI Ethics from Stanford"
      },
      {
        "name": "Marcus Johnson",
        "role": "Tech Journalist",
        "personality": "Curious and conversational",
        "background": "15 years covering AI industry"
      }
    ]
  }' || echo '{}')

echo "✅ Speaker profile ready"
echo ""

# Step 2: Create episode profile
echo "📝 Creating episode profile..."
EPISODE_RESPONSE=$(curl -s -X POST "$API_URL/episode-profiles" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ai_test_episode",
    "briefing": "Create an engaging 10-minute podcast discussing recent AI developments",
    "target_duration_minutes": 10,
    "speaker_profile_name": "ai_ethics_hosts",
    "director_model": "gpt-4o-mini",
    "writer_model": "gpt-4o-mini"
  }' || echo '{}')

echo "✅ Episode profile ready"
echo ""

# Step 3: Generate podcast using NEW workflow
echo "🎬 Generating podcast with NEW multi-agent workflow..."
echo "   This will run: Director → Writers (parallel) → Reviewer → Compliance"
echo ""

GEN_RESPONSE=$(curl -s -X POST "$API_URL/podcasts/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "episode_profile": "ai_test_episode",
    "speaker_profile": "ai_ethics_hosts",
    "episode_name": "AI Safety Test Episode",
    "content": "Recent developments in AI safety research have shown promising results. New techniques for interpretability are helping researchers understand neural networks. However, concerns remain about AI systems in healthcare and criminal justice."
  }')

echo "$GEN_RESPONSE" | jq '.'
echo ""

# Extract job/workflow ID
JOB_ID=$(echo "$GEN_RESPONSE" | jq -r '.job_id // .workflow_id // ""')

if [ -z "$JOB_ID" ]; then
  echo "❌ Failed to get job ID from response"
  exit 1
fi

echo "✅ Workflow started: $JOB_ID"
echo ""

# Step 4: Wait a moment then check status
echo "⏳ Waiting 3 seconds before checking status..."
sleep 3

echo "📊 Checking workflow status..."
STATUS_RESPONSE=$(curl -s "$API_URL/podcasts/jobs/$JOB_ID")
echo "$STATUS_RESPONSE" | jq '.'
echo ""

# Step 5: Show key results
echo "📈 Workflow Summary:"
echo "==================="
echo "$STATUS_RESPONSE" | jq '{
  status: .status,
  stage: .current_stage,
  episode: .episode_name,
  has_director: .has_director_output,
  has_writers: .has_writer_outputs,
  has_reviewer: .has_reviewer_output,
  has_compliance: .has_compliance_output
}'
echo ""

# Step 6: Get full workflow details
echo "🔍 Getting full workflow details..."
WORKFLOW_DETAIL=$(curl -s "$API_URL/agentic-podcasts/workflows/$JOB_ID")

echo ""
echo "✅ Multi-Agent Results:"
echo "======================="

# Check if reviewer ran
HAS_REVIEWER=$(echo "$WORKFLOW_DETAIL" | jq '.reviewer_output != null')
if [ "$HAS_REVIEWER" = "true" ]; then
  echo "✅ Reviewer Agent:"
  echo "$WORKFLOW_DETAIL" | jq '.reviewer_output | {
    overall_score: .overall_score,
    num_issues: (.issues | length),
    has_revised_transcript: (.revised_transcript != null)
  }'
else
  echo "⚠️  Reviewer: Not run or data unavailable"
fi

echo ""

# Check if compliance ran
HAS_COMPLIANCE=$(echo "$WORKFLOW_DETAIL" | jq '.compliance_output != null')
if [ "$HAS_COMPLIANCE" = "true" ]; then
  echo "✅ Compliance Agent:"
  echo "$WORKFLOW_DETAIL" | jq '.compliance_output | {
    approved: .approved,
    risk_level: .overall_risk_level,
    num_flags: (.flags | length)
  }'
else
  echo "⚠️  Compliance: Not run or data unavailable"
fi

echo ""
echo "🎉 Test Complete!"
echo ""
echo "💡 To view the full transcript:"
echo "   curl $API_URL/agentic-podcasts/workflows/$JOB_ID/transcript | jq '.'"
echo ""
echo "💡 To view all workflows:"
echo "   curl $API_URL/agentic-podcasts/workflows | jq '.'"
