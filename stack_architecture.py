"""Classify source layers and framework/database signatures; draw static and reference diagrams."""
from __future__ import annotations
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from architecture import _module, _middle_dir, load_architecture
from codebase import Repo

FRAMEWORKS = {
    'Apache Flex': ('FE', ('apache-flex','flex-sdk','org.apache.flex'), (r'<(?:s|mx):(?:Application|WindowedApplication|Module|View|Panel|Button)\b',r'\bimport\s+(?:mx|spark)\.',r'xmlns:(?:s|mx)='), 'https://flex.apache.org/'),
    'Adobe AIR': ('FE', ('air-sdk','adobe-air','harmanair'), (r'<(?:s|mx):WindowedApplication\b',r'\bflash\.desktop\.',r'\bNativeApplication\b'), 'https://airsdk.harman.com/'),
    'Spring MVC / Core': ('BE', ('org.springframework','spring-webmvc','spring-context','spring-web'), (r'@(?:RestController|Controller|Service|Repository|Autowired|RequestMapping|GetMapping|PostMapping)\b',r'\bimport\s+org\.springframework\.'), 'https://docs.spring.io/spring-framework/reference/'),
    'Spring Boot': ('BE', ('spring-boot','spring-boot-starter'), (r'@SpringBootApplication\b',r'\bSpringApplication\.run\('), 'https://docs.spring.io/spring-boot/reference/'),
    'MyBatis': ('BE', ('mybatis','org.mybatis'), (r'<mapper\s+namespace\s*=',r'@Mapper\b',r'\bimport\s+org\.apache\.ibatis\.'), 'https://mybatis.org/mybatis-3/'),
    'Hibernate / JPA': ('BE', ('hibernate','jakarta.persistence','javax.persistence'), (r'@(?:Entity|Table|PersistenceContext)\b',r'\bimport\s+(?:javax|jakarta)\.persistence\.'), 'https://hibernate.org/orm/'),
    'Struts': ('BE', ('struts','org.apache.struts'), (r'\bimport\s+org\.apache\.struts\.',r'<struts\b'), 'https://struts.apache.org/'),
    'JSF': ('BE', ('jakarta.faces','javax.faces','myfaces'), (r'\bimport\s+(?:javax|jakarta)\.faces\.',r'<h:form\b'), 'https://jakarta.ee/specifications/faces/'),
    'JDBC': ('DB_ACCESS', ('mysql-connector','postgresql','ojdbc','mariadb-java-client'), (r'\bjava\.sql\.(?:Connection|DriverManager|PreparedStatement)\b',r'jdbc:[a-z][a-z0-9]*:'), 'https://docs.oracle.com/javase/tutorial/jdbc/basics/'),
}
DATABASES = {
    'PostgreSQL': (('org.postgresql','postgresql'), (r'jdbc:postgresql:',r'org\.postgresql\.Driver')),
    'MySQL': (('mysql-connector','com.mysql'), (r'jdbc:mysql:',r'com\.mysql\.cj\.jdbc')),
    'MariaDB': (('mariadb-java-client','org.mariadb'), (r'jdbc:mariadb:',r'org\.mariadb\.jdbc')),
    'Oracle Database': (('ojdbc','oracle.jdbc'), (r'jdbc:oracle:',r'oracle\.jdbc\.')),
    'Microsoft SQL Server': (('mssql-jdbc','sqljdbc','com.microsoft.sqlserver'), (r'jdbc:sqlserver:',r'com\.microsoft\.sqlserver\.jdbc')),
    'SQLite': (('sqlite-jdbc','org.xerial'), (r'jdbc:sqlite:',r'org\.sqlite\.JDBC')),
    'H2': (('com.h2database','h2database'), (r'jdbc:h2:',r'org\.h2\.Driver')),
    'DB2': (('com.ibm.db2','db2jcc'), (r'jdbc:db2:',r'com\.ibm\.db2\.jcc')),
}
REFERENCE_STRUCTURE = {
    'Apache Flex': ['Application/Module MXML','View / reusable component MXML','ActionScript event handler / presenter','Model / value object','Service or RemoteObject proxy'],
    'Adobe AIR': ['Application descriptor and startup','Desktop lifecycle / native integration','UI MXML or ActionScript component','Remote data access'],
    'Spring MVC / Core': ['Controller / endpoint','Service / business rules','Repository / DAO','Domain / DTO','Configuration / injection'],
    'Spring Boot': ['Application bootstrap / configuration','Controller / API','Service','Repository','Domain / DTO','Resources and tests'],
    'MyBatis': ['Mapper interface','Mapper XML or annotation SQL','Domain/DTO mapping','SqlSession/data-source configuration'],
    'Hibernate / JPA': ['Entity','Repository/DAO','Persistence configuration','Transaction boundary'],
    'Struts': ['Action / form','Action mapping configuration','JSP/templated view','Service / DAO'],
    'JSF': ['Facelets view','Backing bean','Service / domain','Persistence layer'],
    'JDBC': ['Connection/DataSource','DAO or repository','PreparedStatement / mapping','Transactions'],
}

def _layer(path,source):
    ext=Path(path).suffix.lower()
    if ext in ('.as','.mxml','.css','.js','.ts','.tsx','.jsx','.vue','.html'):return 'FE'
    if ext=='.java':return 'BE'
    if ext=='.sql':return 'DB'
    if ext in ('.jsp','.jspx'):return 'FE (server-rendered)'
    if ext in ('.xml','.properties','.yaml','.yml'):
        if re.search(r'<mapper\b|<sqlMap\b|<hibernate-mapping\b',source,re.I):return 'DB/BE'
    return 'SHARED/UNKNOWN'

def _role(path,source,layer):
    name=Path(path).stem.lower()
    if layer=='FE':
        if any(x in name for x in ('screen','view','window','page','form')):return 'View / Screen'
        if any(x in name for x in ('controller','presenter','mediator','event','action')):return 'Event / Controller'
        if any(x in name for x in ('model','dto','valueobject')):return 'Model / Value Object'
        if any(x in name for x in ('proxy','remote','gateway','service')) or 'RemoteObject' in source:return 'Remote / Data Service'
        if path.endswith('.mxml'):return 'View / Component'
    if layer=='BE':
        if any(x in name for x in ('controller','endpoint','resource')) or re.search(r'@(?:RestController|Controller)\b',source):return 'Controller / Endpoint'
        if 'service' in name or re.search(r'@Service\b',source):return 'Service'
        if any(x in name for x in ('repository','dao','mapper')) or re.search(r'@(?:Mapper|Repository)\b',source):return 'Repository / DAO / Mapper'
        if any(x in name for x in ('entity','dto','model','domain')) or '@Entity' in source:return 'Entity / DTO / Domain'
        if any(x in name for x in ('config','security','filter')):return 'Configuration / Security'
    if layer=='DB/BE':return 'Mapper XML'
    if layer=='DB':return 'SQL / Schema'
    return 'Unclassified source object'

def _reference_matches(framework, expected_role, objects):
    role=expected_role.lower()
    categories=[]
    if any(x in role for x in ('controller','endpoint','action / form')):categories=['Controller / Endpoint','Event / Controller']
    elif any(x in role for x in ('repository','dao','mapper interface')):categories=['Repository / DAO / Mapper']
    elif 'mapper xml' in role or 'annotation sql' in role:categories=['Mapper XML']
    elif any(x in role for x in ('service','business rules','service / domain')):categories=['Service','Remote / Data Service']
    elif any(x in role for x in ('view','component','mxml','facelets','jsp','ui ')):categories=['View / Screen','View / Component']
    elif any(x in role for x in ('event handler','presenter')):categories=['Event / Controller']
    elif any(x in role for x in ('entity','dto','model','domain','value object')):categories=['Entity / DTO / Domain','Model / Value Object']
    elif any(x in role for x in ('configuration','injection','bootstrap','startup','application descriptor','data-source','datasource','sqlsession','persistence')):categories=['Configuration / Security']
    elif 'remote' in role or 'proxy' in role:categories=['Remote / Data Service']
    elif 'preparedstatement' in role or 'connection/' in role:categories=['Repository / DAO / Mapper']
    matches=[]
    for obj in objects:
        if framework in ('Apache Flex','Adobe AIR') and obj['layer']!='FE':continue
        if framework not in ('Apache Flex','Adobe AIR') and obj['layer'] not in ('BE','DB/BE'):continue
        if any(k in obj['roles'] for k in categories):matches.append(obj['file'])
        elif 'mapper xml' in role and obj['file'].lower().endswith('mapper.xml'):matches.append(obj['file'])
        elif 'application descriptor' in role and obj['file'].lower().endswith('application.xml'):matches.append(obj['file'])
    return sorted(set(matches))


# Static architecture diagram colors: visual categories, not runtime claims.
LAYER_COLORS = {
    'FE': ('#fff0dc', '#b96c12'),
    'BE': ('#e4f0ff', '#416eaa'),
    'DB': ('#e2f3e7', '#3a8556'),
    'SHARED': ('#eef0f3', '#7a8491'),
}


def _diagram_layer(name):
    if name.startswith('FE') or name in ('Apache Flex', 'Adobe AIR'):
        return 'FE'
    if name.startswith('BE') or name in ('Spring MVC / Core', 'Spring Boot', 'MyBatis',
                                        'Hibernate / JPA', 'Struts', 'JSF', 'JDBC'):
        return 'BE'
    if name.startswith('DB') or name in ('DB/BE',):
        return 'DB'
    return 'SHARED'


def _ordered_components(groups, links, reference=False, lane_mode=False):
    """A deterministic layout order; do not infer missing graph edges."""
    names = list(groups)
    if lane_mode:
        return [(lane, [n for n in names if _diagram_layer(n) == lane])
                for lane in ('FE', 'BE', 'DB', 'SHARED')]
    if reference:
        grouped = {}
        for name in names:
            framework = name.split(': ', 1)[0] if ': ' in name else '(Unmatched)'
            grouped.setdefault(framework, []).append(name)
        return list(grouped.items())
    adjacency = defaultdict(Counter)
    for (src, dst), weight in links.items():
        if src in groups and dst in groups and src != dst:
            adjacency[src][dst] += weight
            adjacency[dst][src] += weight
    ordered = []
    remaining = set(names)
    while remaining:
        start = sorted(remaining, key=lambda n: (-sum(adjacency[n].values()), n))[0]
        queue = [start]
        while queue:
            curr = queue.pop(0)
            if curr not in remaining:
                continue
            remaining.remove(curr)
            ordered.append(curr)
            queue.extend(sorted((n for n in adjacency[curr] if n in remaining),
                                key=lambda n: (-adjacency[curr][n], n)))
    return [('Components', ordered)]


def _draw(destination, title, groups, links, reference=False, lane_mode=False):
    """Draw.io left-to-right lane/framework layout with larger, editable arrows."""
    root = ET.Element('mxfile', {'host': 'app.diagrams.net', 'type': 'device'})
    diagram = ET.SubElement(root, 'diagram', {'id': 'stack', 'name': title})
    columns = [(heading, values) for heading, values in
               _ordered_components(groups, links, reference=reference, lane_mode=lane_mode) if values]
    if not columns:
        columns = [('Unclassified', list(groups))]
    box_w, box_h, gap_y = 470, 154, 54
    lane_w, lane_gap, top = 520, 90, 150
    max_rows = max(len(values) for _, values in columns)
    page_w = max(1600, 100 + len(columns) * (lane_w + lane_gap))
    page_h = max(1100, top + max_rows * (box_h + gap_y) + 90)
    model = ET.SubElement(diagram, 'mxGraphModel', {
        'dx': '1400', 'dy': '900', 'grid': '1', 'gridSize': '10', 'page': '1',
        'pageWidth': str(page_w), 'pageHeight': str(page_h)
    })
    cells = ET.SubElement(model, 'root')
    ET.SubElement(cells, 'mxCell', {'id': '0'})
    ET.SubElement(cells, 'mxCell', {'id': '1', 'parent': '0'})
    ids = {}
    for col, (section, items) in enumerate(columns):
        x = 60 + col * (lane_w + lane_gap)
        layer = section if lane_mode else _diagram_layer(section)
        fill, border = LAYER_COLORS.get(layer, LAYER_COLORS['SHARED'])
        header = ET.SubElement(cells, 'mxCell', {
            'id': f'group{col}', 'value': section,
            'style': f'rounded=1;whiteSpace=wrap;html=0;fillColor={fill};strokeColor={border};'
                     'fontSize=20;fontStyle=1;align=center;verticalAlign=middle;strokeWidth=2;',
            'vertex': '1', 'parent': '1'
        })
        ET.SubElement(header, 'mxGeometry', {
            'x': str(x), 'y': '46', 'width': str(box_w), 'height': '58', 'as': 'geometry'
        })
        for row, name in enumerate(items):
            meta = groups[name]
            ids[name] = f'n{len(ids)+2}'
            if isinstance(meta, dict):
                count = meta.get('count', 0)
                examples = meta.get('examples', [])[:3]
                label = meta.get('informational') or f'{name}\n{count} source objects'
                if examples:
                    label += '\n' + '\n'.join(examples)
            else:
                label = f'{name}\n{meta} objects'
            node = ET.SubElement(cells, 'mxCell', {
                'id': ids[name], 'value': label,
                'style': f'rounded=1;whiteSpace=wrap;html=0;fillColor={fill};strokeColor={border};'
                         'fontSize=14;fontStyle=1;align=center;verticalAlign=middle;spacing=10;'
                         'strokeWidth=2;arcSize=10;',
                'vertex': '1', 'parent': '1'
            })
            ET.SubElement(node, 'mxGeometry', {
                'x': str(x), 'y': str(top + row * (box_h + gap_y)),
                'width': str(box_w), 'height': str(box_h), 'as': 'geometry'
            })
    style = ('edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;'
             'jettySize=auto;html=0;endArrow=block;endFill=1;endSize=24;'
             'strokeWidth=3;strokeColor=#63758a;fontSize=14;'
             'labelBackgroundColor=#ffffff;')
    if reference:
        style += 'dashed=1;dashPattern=8 5;strokeColor=#888888;'
    for i, ((source, target), count) in enumerate(sorted(links.items(),
                                key=lambda item: (-item[1], item[0]))[:180]):
        if source not in ids or target not in ids or source == target:
            continue
        edge = ET.SubElement(cells, 'mxCell', {
            'id': f'e{i+1000}',
            'value': 'Reference only' if reference else f'{count} static refs',
            'style': style, 'source': ids[source], 'target': ids[target],
            'edge': '1', 'parent': '1'
        })
        ET.SubElement(edge, 'mxGeometry', {'relative': '1', 'as': 'geometry'})
    ET.ElementTree(root).write(destination, encoding='utf-8', xml_declaration=True)


def export_stack_architecture(repo:Repo,out,graph=None,verbose=True):
    """Identify FE/BE/DB and draw observed static vs conceptual reference structures."""
    dest=Path(out).expanduser().resolve()
    dest.mkdir(parents=True,exist_ok=True)
    middle=_middle_dir(dest)
    graph=graph or load_architecture(repo,dest)
    if graph is None:raise ValueError('architecture graph missing/stale: run architecture first')
    framework_hits=defaultdict(list); db_hits=defaultdict(list)
    layers=Counter();module_layers=defaultdict(Counter);roles=defaultdict(Counter)
    objects=[];source_errors=[];path_layer={};path_role={}
    for dep in graph.get('dependencies',[]):
        lib=dep['library'].lower()
        for name,(layer,needles,_,_) in FRAMEWORKS.items():
            if any(x in lib for x in needles):
                framework_hits[name].append({'source':dep['declared_in'],'kind':'declared-dependency','match':dep['library']})
        for name,(needles,_) in DATABASES.items():
            if any(x in lib for x in needles):
                db_hits[name].append({'source':dep['declared_in'],'kind':'declared-driver','match':dep['library']})
    for path,_,_ in graph['source_inventory']:
        try:source=repo._read(repo._safe(path))
        except (OSError,ValueError) as error:
            source_errors.append({'path':path,'error':str(error)[:150]})
            continue
        layer=_layer(path,source);role=_role(path,source,layer)
        path_layer[path]=layer;path_role[path]=role
        layers[layer]+=1;module_layers[_module(path)][layer]+=1;roles[layer][role]+=1
        obj={'file':path,'module':_module(path),'layer':layer,'roles':[role],'frameworks':[],'evidence':[]}
        for name,(_,_,patterns,_) in FRAMEWORKS.items():
            for pattern in patterns:
                match=re.search(pattern,source,re.I|re.M)
                if match:
                    ev={'source':f'{path}:{source.count(chr(10),0,match.start())+1}',
                        'kind':'source-pattern','match':match.group(0)[:90]}
                    if len(framework_hits[name])<120:framework_hits[name].append(ev)
                    obj['frameworks'].append(name);obj['evidence'].append(ev)
                    break
        for name,(_,patterns) in DATABASES.items():
            for pattern in patterns:
                match=re.search(pattern,source,re.I|re.M)
                if match:
                    if len(db_hits[name])<100:
                        db_hits[name].append({'source':f'{path}:{source.count(chr(10),0,match.start())+1}',
                                              'kind':'source-pattern','match':match.group(0)[:90]})
                    break
        if len(objects)<20000:objects.append(obj)
    frameworks={}
    for name,(layer,_,_,url) in FRAMEWORKS.items():
        hits=framework_hits[name]
        if hits:frameworks[name]={'layer':layer,
            'confidence':'source-signature' if any(x['kind']=='source-pattern' for x in hits) else 'declared-dependency-only',
            'evidence':hits[:15],'evidence_count':len(hits),
            'reference':url,'expected_objects':REFERENCE_STRUCTURE.get(name,[])}
    dbs={}
    for name,hits in db_hits.items():
        if hits:dbs[name]={'confidence':'connection-string-or-driver' if any(x['kind']=='source-pattern' for x in hits) else 'driver-dependency-only',
                           'evidence':hits[:12],'evidence_count':len(hits)}
    within=defaultdict(Counter);across=Counter()
    for edge in graph.get('edges',[]):
        src,dst=edge['from'],edge['to']
        a,b=path_layer.get(src),path_layer.get(dst)
        if a and b and a==b and a in ('FE','BE','DB/BE'):
            x,y=path_role[src],path_role[dst]
            if x!=y:within[a][x,y]+=1
        elif a and b and a!=b:across[a,b]+=1
    for layer,file in [('FE','frontend_architecture.drawio'),('BE','backend_architecture.drawio')]:
        groups=dict(roles[layer].most_common(28)) or {f'No confirmed {layer} source':0}
        _draw(dest/file,layer+' observed static architecture',groups,within[layer])
    reference_coverage={}
    for layer,filename in [('FE','frontend_reference.drawio'),('BE','backend_reference.drawio')]:
        matched_nodes={};reference_edges=Counter()
        for framework,info in frameworks.items():
            if info['layer']!=layer:continue
            found=[]
            for expected in info['expected_objects']:
                matches=_reference_matches(framework,expected,objects)
                key=f'{framework}: {expected}'
                reference_coverage[key]={'layer':layer,'framework':framework,
                    'expected_role':expected,'objects':matches,'status':'found' if matches else 'not_found'}
                if matches:
                    matched_nodes[key]={'count':len(matches),'examples':matches[:3]}
                    found.append(key)
            for prev,current in zip(found,found[1:]):reference_edges[prev,current]=1
        if matched_nodes:
            _draw(dest/filename,layer+' reference grounded in scanned source',
                  dict(list(matched_nodes.items())[:60]),reference_edges,reference=True)
        else:
            _draw(dest/filename,layer+' no matching source objects',
                  {'No matching source objects':{'informational':'No framework reference roles mapped to source files'}},
                  Counter())
    _draw(dest/'fe_be_architecture.drawio','Observed cross-layer static references',dict(layers),across,lane_mode=True)
    result={'reference_role_coverage':reference_coverage,'layers':dict(layers),'module_layers':{k:dict(v) for k,v in module_layers.items()},
            'frameworks':frameworks,'databases':dbs,'objects':objects,
            'roles':{k:dict(v) for k,v in roles.items()},
            'cross_layer_static_edges':{f'{a} -> {b}':n for (a,b),n in across.items()},
            'read_errors':source_errors,'graph_version':graph.get('architecture_version'),
            'limitations':['No verified runtime call graph','No database signature does not prove database absent',
                           'Declared dependencies are not evidence of runtime initialization']}
    (middle/'stack_architecture.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    report=['# FE / BE / Database — Framework & Architecture Analysis','',
            '> Observed = source evidence; Expected = framework guidance; imports do not prove runtime calls.','',
            '## Mục lục','','- [Phân loại FE BE DB](#phân-loại-fe-be-db)',
            '- [Framework và bằng chứng](#framework-và-bằng-chứng)',
            '- [Database](#database)','- [Objects và cấu trúc khuyến nghị](#objects-và-cấu-trúc-khuyến-nghị)',
            '- [Sơ đồ](#sơ-đồ)','- [Giới hạn](#giới-hạn)','',
            '## Phân loại FE BE DB','','| Nhóm | File |','|---|---:|']
    report.extend(f'| {k} | {v} |' for k,v in layers.most_common())
    report+=['','### FE/BE/DB theo module','','| Module | FE | BE | DB | Shared / Unknown |','|---|---:|---:|---:|---:|']
    for module,count in sorted(module_layers.items()):
        report.append(f'| '+ chr(96)+module+chr(96)+f' | {count["FE"]+count["FE (server-rendered)"]} | {count["BE"]} | {count["DB"]+count["DB/BE"]} | {count["SHARED/UNKNOWN"]} |')
    report+=['','## Framework và bằng chứng','','| Framework | Layer | Confidence | Source |','|---|---|---|---|']
    for name,item in frameworks.items():
        refs=', '.join(x['source'] for x in item['evidence'][:3])
        report.append(f'| [{name}]({item["reference"]}) | {item["layer"]} | {item["confidence"]} | {refs} |')
    report+=['','## Database','','| Database | Evidence | Source |','|---|---|---|']
    for name,item in dbs.items():report.append(f'| {name} | {item["confidence"]} | '+', '.join(x['source'] for x in item['evidence'][:3])+' |')
    if not dbs:report.append('| Not identified | No confirmed driver / URL | |')
    report+=['','## Objects và cấu trúc khuyến nghị','','| Layer | Object role | Files |','|---|---|---:|']
    for layer,count in roles.items():
        for name,n in count.most_common(30):report.append(f'| {layer} | {name} | {n} |')
    for name,item in frameworks.items():
        report+=['',f'### {name} — Reference structure','','Expected pattern, not proof that source objects exist.','']
        report.extend('- '+x for x in item['expected_objects'])
        report.append('- Documentation: '+item['reference'])
    report+=['','### Đối chiếu Reference với source','',
             '| Framework | Vai trò tham khảo | Object tìm thấy | File minh họa |',
             '|---|---|---:|---|']
    for item in reference_coverage.values():
        examples=', '.join(chr(96)+p+chr(96) for p in item['objects'][:2]) or 'Không tìm thấy trong source đã quét'
        report.append(f'| {item["framework"]} | {item["expected_role"]} | {len(item["objects"])} | {examples} |')
    report+=['','## Sơ đồ','','- frontend_architecture.drawio / backend_architecture.drawio — observed static object roles.',
             '- fe_be_architecture.drawio — observed cross-layer references only.',
             '- frontend_reference.drawio / backend_reference.drawio — expected patterns drawn with dashed arrows.',
             '- Machine-readable details: middle-files/stack_architecture.json.','','## Giới hạn','',
             '- Only source signatures, declared libraries and regex naming rules are analyzed.',
             '- RemoteObject, dependency injection, runtime calls and dynamic SQL are not fully traced.',
             '- A database cannot be identified reliably without relevant config or driver evidence.',
             '- Source file size and extension scanner exclusions still apply.']
    (dest/'stack_architecture.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
    if verbose:print('[Stack] Generated FE, BE and database architecture evidence and diagrams.',flush=True)
    return {'stack_report':str(dest/'stack_architecture.md'),
        'fe_diagram':str(dest/'frontend_architecture.drawio'),
        'be_diagram':str(dest/'backend_architecture.drawio'),
        'fe_reference':str(dest/'frontend_reference.drawio'),
        'be_reference':str(dest/'backend_reference.drawio'),
        'fe_be_diagram':str(dest/'fe_be_architecture.drawio'),
        'stack_json':str(middle/'stack_architecture.json'),
        'frameworks_detected':list(frameworks),'databases_detected':list(dbs)}
