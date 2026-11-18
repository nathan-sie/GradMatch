"""Render the three-page submission report; reportlab is an optional authoring dependency."""
import argparse
from html import escape
import json
from pathlib import Path


def render(root,output):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.styles import ParagraphStyle,getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak
    navy=colors.HexColor('#172B4D');blue=colors.HexColor('#265D8C');muted=colors.HexColor('#55657A')
    pale=colors.HexColor('#EFF4F8');line=colors.HexColor('#D8E0E8')
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Hero',fontName='Helvetica-Bold',fontSize=24,leading=28,textColor=navy,spaceAfter=10))
    styles.add(ParagraphStyle(name='Deck',fontName='Helvetica',fontSize=11,leading=16,textColor=muted,spaceAfter=14))
    styles.add(ParagraphStyle(name='H',fontName='Helvetica-Bold',fontSize=12.5,leading=16,textColor=blue,spaceBefore=13,spaceAfter=7,keepWithNext=True))
    styles.add(ParagraphStyle(name='B',fontName='Helvetica',fontSize=9.7,leading=13.8,textColor=navy,spaceAfter=8))
    styles.add(ParagraphStyle(name='SmallNote',fontName='Helvetica',fontSize=8.1,leading=11,textColor=muted,spaceAfter=7))
    styles.add(ParagraphStyle(name='Cell',fontName='Helvetica',fontSize=8.3,leading=11,textColor=navy))
    styles.add(ParagraphStyle(name='CellHead',fontName='Helvetica-Bold',fontSize=8.1,leading=10.5,textColor=colors.white))
    styles.add(ParagraphStyle(name='CodeCell',fontName='Courier',fontSize=7.8,leading=10.5,textColor=navy,wordWrap='CJK'))
    summary=json.loads((root/'docs/verification/h5/results/summary.json').read_text(encoding='utf-8'))
    case=json.loads((root/'docs/verification/h6/failure_case.json').read_text(encoding='utf-8'))
    failure=(root/'homework/FAILURE_ANALYSIS.md').read_text(encoding='utf-8').split('\n\n')[1]
    story=[]
    def p(text,style='B'):return Paragraph(escape(text),styles[style])
    def add(text,style='B'):story.append(p(text,style))
    def heading(text):add(text,'H')
    def table(rows,widths,*,head=True,code_columns=(),compact=False):
        formatted=[]
        for row_i,row in enumerate(rows):
            formatted.append([p(str(value),'CellHead' if row_i==0 and head else 'CodeCell' if col in code_columns else 'Cell')
                for col,value in enumerate(row)])
        t=Table(formatted,colWidths=widths,hAlign='LEFT',repeatRows=1 if head else 0)
        commands=[('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),8),
            ('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),4 if compact else 7),
            ('BOTTOMPADDING',(0,0),(-1,-1),4 if compact else 7),('LINEBELOW',(0,-1),(-1,-1),0.6,line)]
        if head:commands.append(('BACKGROUND',(0,0),(-1,0),navy))
        for i in range(1 if head else 0,len(rows)):
            if i%2:commands.append(('BACKGROUND',(0,i),(-1,i),pale))
        t.setStyle(TableStyle(commands));story.append(t);story.append(Spacer(1,8))
    add('GRADMATCH  /  COURSE HOMEWORK','SmallNote')
    add('Evaluation Harness','Hero')
    add('50 frozen tasks. One baseline and three Agent executions per task.\\nActual results collected November 17, 2026.'.replace('\\n',' '),'Deck')
    add('The baseline follows fixed search, record retrieval and checks before one answer call per user turn. The Agent selects native tool calls from observations. Both use the same ten-program snapshot, model, rules and resource ceilings.')
    heading('1  Results on the prescribed 50 tasks')
    rows=[['System','Accuracy','Passes','Avg calls','Mean (s)','p95 (s)','Avg tokens']]
    for item in summary['comparison']:
        rows.append(['Baseline' if item['label']=='Fixed baseline' else 'Agent: repeat 1',
            f"{item['accuracy']:.0%}",f"{item['passed']}/50",f"{item['avg_turns']:.2f}",
            f"{item['avg_latency_ms']/1000:.3f}",f"{item['p95_latency_ms']/1000:.3f}",f"{item['avg_tokens']:,.2f}"])
    table(rows,[97,60,48,60,69,66,100])
    add('Repeat 1 was designated before execution. Calls include setup and interpretation; latency includes candidate tools/waits and failed executions, excludes judging, and uses nearest-rank p95. Tokens are input plus output; cached input is not added again.','SmallNote')
    heading('2  Repeated-run reliability')
    table([['Measure','Observed'],['pass@3: at least one pass','49/50 = 98%'],
        ['pass^3: all three pass','38/50 = 76%'],['Tasks with mixed outcomes','11/50'],
        ['Agent pooled, separately labelled','131/150 = 87.33%']],[310,190])
    add('Flip IDs: t18, t26, t28, t29, t33, t41, t42, t43, t44, t45, t49. Task t27 failed all three draws. These are observed vectors, not the cube of an aggregate accuracy.','SmallNote')
    heading('3  Where the difference comes from')
    table([['Task type','Baseline','Agent repeat 1'],['Exact','18/18','18/18'],
        ['First-tool-call','1/8','8/8'],['Rubric','16/20','17/20'],['Unanswerable','4/4','4/4']],[250,125,125])
    add('Seven of the eight additional primary passes are first-tool cases. Exact and unanswerable primary results are equal; rubric performance differs by one task. The Agent uses more calls, time and tokens. This small authored set does not establish a general 16-point admission-advising gain.','SmallNote')
    story.append(PageBreak())
    add('One Traced Agent Failure','Hero')
    add('t26 / Agent repeat 2 / procedural first-call failure','Deck')
    add(failure)
    heading('Evidence sequence')
    table([['Step','Actual event','Result'],['1','User requests check_program for uci-mcs-irvine at profile version 1.','Expected direct first check.'],
        ['2','First model action: get_program with the same program_id.','Lookup succeeds; first-action requirement is missed.'],
        ['3','Second model action: check_program with profile_version=1.','Check succeeds; IELTS speaking 5.5 is below 6.'],
        ['4','Final answer explains the module failure and keeps the program out.','Application validation accepts the answer.'],
        ['5','Deterministic first_tool_call criterion is false.','Later correctness cannot repair the ordering failure.']],[43,282,175],compact=True)
    heading('Trace and grade identifiers')
    table([['Record','Identifier'],['Candidate trace',case['trace_id']],
        ['First model span',case['first_model_span_id']],['First tool span',case['first_tool_span_id']],
        ['Second tool span',case['second_tool_span_id']]], [122,378],code_columns=(1,),compact=True)
    add('Full evidence in the ZIP:','SmallNote')
    add('docs/verification/h5/formal/entries/t26--react--r2/candidate.json','CodeCell')
    add('docs/verification/h5/formal/entries/t26--react--r2/grade.json','CodeCell')
    add('Machine-checked facts: docs/verification/h6/failure_case.json','SmallNote')
    heading('A future regression, outside the benchmark')
    add('The three t26 outcomes were [pass, fail, pass]. A candidate-only regression at profile version 3 and a separate expected-call reference test the general direct-check ordering rule. No proposed policy fix was implemented, no extra model request was made for this regression, and no frozen score was changed.')
    story.append(PageBreak())
    add('Reproduce and Review','Hero')
    add('Offline verification first; new model draws require explicit enablement.','Deck')
    heading('Frozen experiment')
    add('Model: gpt-5.4-mini-2026-03-17. Assessment date: 2026-11-16. The 50-task set contains 18 exact, 8 tool, 20 rubric and 4 unanswerable tasks; 11 have overlapping edge-case tags and 3 have follow-ups. Caps: 8 candidate calls, 12 tool calls and 120 seconds per task. No automatic retries.')
    add('Source: 61d7b844bf201ed55e12196678779c8c63807ba9','CodeCell')
    add('Experiment: bf76953d-36e5-46e9-a73b-34df32e0e697','CodeCell')
    add('The source and plan were pinned before execution. All 200 candidate/grade pairs are preserved, including 8 validation-rejected outputs. There are 170 passes, 30 failures, zero unresolved results and zero judge errors. Verification checked 200 isolated traces, 569 provider response IDs and 934 exact evidence items. All 244 pre-freeze regression tests passed.')
    heading('Actual requests and estimated cost')
    table([['Stream','Requests','Input tokens','Output tokens','USD'],
        ['Candidate','409','1,699,158','47,723','0.86272200'],['Judge','160','1,227,393','36,984','1.06597755'],
        ['Formal total','569','Separate','Separate','1.92869955']],[95,60,120,110,115])
    add('All H5 development, failures and recalibration add USD 0.65360760; H5 total estimate: USD 2.58230715. Usage is measured. Cost uses the dated project price lock and is not an invoice. Candidate efficiency excludes judge usage.','SmallNote')
    heading('Offline quick start')
    add('Use Python 3.12 and the locked dependencies. From the extracted ZIP root:','B')
    add('python -m scripts.homework.validate_tasks','CodeCell')
    add('python eval.py --dry-run --experiment-dir work/review-plan','CodeCell')
    add('To recompute every result, use the full summary command in README.md. No API key is needed for saved-result summaries. A new paid experiment requires --live-model and a fresh labelled directory.','SmallNote')
    heading('Limits and package contents')
    add('The corpus is small and authored. Judge and candidate share a model family; only five binary human labels were obtained, with one skipped example. A saved development answer received different semantic judgments, so repeat stability includes both candidate and judge variation. The selected failure is deterministic and avoids that ambiguity.')
    add('The ZIP includes tasks.jsonl, eval.py, source, snapshots, references, results, flip vectors, full formal/development records and byte hashes. It excludes keys, local SQLite, virtual environments and the lecture PDF. The final project larger/safety benchmark and live web/PDF tools remain separate. Main and the public app are unchanged.','SmallNote')
    output.parent.mkdir(parents=True,exist_ok=True)
    def decorate(canvas,doc):
        canvas.saveState()
        canvas.setStrokeColor(line);canvas.setLineWidth(.6);canvas.line(46,45,566,45)
        canvas.setFillColor(muted);canvas.setFont('Helvetica',7.5)
        canvas.drawString(46,31,'GradMatch | Frozen 50-task evaluation | 17 Nov 2026')
        canvas.drawRightString(566,31,f'{doc.page} / 3')
        canvas.restoreState()
    doc=SimpleDocTemplate(str(output),pagesize=(612,792),leftMargin=46,rightMargin=46,topMargin=40,bottomMargin=58,
        title='GradMatch Evaluation Harness Report',author='GradMatch project team')
    doc.build(story,onFirstPage=decorate,onLaterPages=decorate)
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[2]
    output=args.output or root/'output/pdf/GradMatch_Eval_Report.pdf'
    print(render(root,output))


if __name__=='__main__':main()
