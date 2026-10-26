"""Identify FE/BE/DB technology, source objects and observed architecture evidence.

This is a static inventory, NOT a runtime call graph or proof of framework use.
Generates Draw.io views for observed FE, BE and a conceptual cross-layer overview.
"""
from __future__ import annotations
import json
import re
import xml.etree.ElementTree as ET
import math
from collections import Counter, defaultdict
from pathlib import Path

from architecture import _module, load_architecture, _middle_dir
from codebase import Repo

FRAMEWORKS = {
    'Apache Flex': ('FE', ('org.apache.flex','apache-flex','flex-sdk'), (r'<(?:s|mx):(?:Application|WindowedApplication|Module|View|Panel|Button)\b', r'\bimport\s+(?:mx|spark)\.', r'xmlns:(?:s|mx)='), 'https://flex.apache.org/doc/flex/using/flx_mxml_mx.html'),
    'Adobe AIR': ('FE', ('air-sdk','adobe-air','harmanair'), (r'<(?:s|mx):WindowedApplication\b',r'\bflash\.desktop\.',r'\bflash\.filesystem\.',r'\bNativeApplication\b'), 'https://flex.apache.org/doc/flex/using/flx_intro_int.html'),
    'Spring MVC / Core': ('BE', ('org.springframework','spring-webmvc','spring-context','spring-web'), (r'@(?:RestController|Controller|Service|Repository|Autowired|RequestMapping|GetMapping|PostMapping)\b',r'\bimport\s+org\.springframework\.'), 'https://docs.spring.io/spring-framework/reference/core/beans/classpath-scanning.html'),
    'Spring Boot': ('BE', ('spring-boot','spring-boot-starter'), (r'@SpringBootApplication\b',r'\bSpringApplication\.run\('), 'https://docs.spring.io/spring-boot/reference/using/structuring-your-code.html'),
    'MyBatis': ('BE', ('mybatis','org.mybatis'), (r'<mapper\s+namespace\s*=',r'@Mapper\b',r'\bimport\s+org\.apache\.ibatis\.'), 'https://mybatis.org/mybatis-3/sqlmap-xml.html'),
    'Hibernate / JPA': ('BE', ('hibernate','jakarta.persistence','javax.persistence'), (r'@(?:Entity|Table|PersistenceContext)\b',r'\bimport\s+(?:javax|jakarta)\.persistence\.'), 'https://docs.jboss.org/hibernate/orm/current/quickstart/html_single/'),
    'Struts': ('BE', ('struts','org.apache.struts'), (r'\bimport\s+org\.apache\.struts\.',r'<struts\b',r'<action-mappings\b'), 'https://struts.apache.org/'),
    'JSF': ('BE', ('jakarta.faces','javax.faces','myfaces'), (r'\bimport\s+(?:javax|jakarta)\.faces\.',r'<h:form\b',r'<f:view\b'), 'https://jakarta.ee/specifications/faces/'),
    'JDBC': ('DB_ACCESS', ('mysql-connector','postgresql','ojdbc','mariadb-java-client'), (r'\bjava\.sql\.(?:Connection|DriverManager|PreparedStatement)\b',r'jdbc:[a-z][a-z0-9]*:'), 'https://docs.oracle.com/javase/tutorial/jdbc/basics/index.html'),
}
DATABASES = {
    'PostgreSQL': (('org.postgresql','postgresql'), (r'jdbc:postgresql:',r'org\.postgresql\.Driver',r'org\.postgresql\.Driver')),
    'MySQL': (('mysql-connector','com.mysql'), (r'jdbc:mysql:',r'com\.mysql\.cj\.jdbc',r'com\.mysql\.jdbc\.Driver')),
    'MariaDB': (('mariadb-java-client','org.mariadb'), (r'jdbc:mariadb:',r'org\.mariadb\.jdbc',r'org\.mariadb\.jdbc')),
    'Oracle Database': (('ojdbc','oracle.jdbc'), (r'jdbc:oracle:',r'oracle\.jdbc\.',r'\bOracleDriver\b')),
    'Microsoft SQL Server': (('mssql-jdbc','sqljdbc','com.microsoft.sqlserver'), (r'jdbc:sqlserver:',r'com\.microsoft\.sqlserver\.jdbc')),
    'SQLite': (('sqlite-jdbc','org.xerial'), (r'jdbc:sqlite:',r'org\.sqlite\.JDBC')),
    'H2': (('com.h2database','h2database'), (r'jdbc:h2:',r'org\.h2\.Driver')),
    'DB2': (('com.ibm.db2','db2jcc'), (r'jdbc:db2:',r'com\.ibm\.db2\.jcc')),
}
OBJECT_RULES = [
    ('FE', 'View / Screen', r'(?i)(?:screen|view|window|page|form|panel)(?:\.mxml|\.as)$'),
    ('FE', 'Event / Controller', r'(?i)(?:controller|presenter|mediator|event|action|command)\.as$'),
    ('FE', 'Model / Value Object', r'(?i)(?:model|vo|dto|valueobject)\.as$'),
    ('FE', 'Remote / Data Service', r'(?i)(?:proxy|delegate|remote|service|gateway)\.as$'),
    ('BE', 'Controller / Endpoint', r'(?i)(?:controller|endpoint|resource|action)\.java$'),
    ('BE', 'Service', r'(?i)(?:service|serviceimpl|facade)\.java$'),
    ('BE', 'Repository / DAO / Mapper', r'(?i)(?:repository|dao|mapper)\.java$'),
    ('BE', 'Entity / DTO / Domain', r'(?i)(?:entity|dto|vo|model|domain|bean)\.java$'),
    ('BE', 'Configuration / Security', r'(?i)(?:config|configuration|security|filter)\.java$'),
    ('BE', 'Mapper XML', r'(?i)(?:mapper|sqlmap)\.xml$'),
]
REFERENCE_STRUCTURE = {
    'Apache Flex': ['Application/Module MXML', 'View / reusable component MXML', 'ActionScript event handler / presenter', 'Model / value object', 'Service or RemoteObject proxy'],
    'Adobe AIR': ['Application descriptor and startup', 'Desktop lifecycle / native integration', 'UI MXML or ActionScript component', 'Remote data access'],
    'Spring MVC / Core': ['Controller / endpoint', 'Service / business rules', 'Repository / DAO', 'Domain / DTO', 'Configuration / injection'],
    'Spring Boot': ['Application bootstrap / configuration', 'Controller / API', 'Service', 'Repository', 'Domain / DTO', 'Resources and tests'],
    'MyBatis': ['Mapper interface', 'Mapper XML or annotation SQL', 'Domain/DTO mapping', 'SqlSession/data-source configuration'],
    'Hibernate / JPA': ['Entity', 'Repository/DAO', 'Persistence configuration', 'Transaction boundary'],
    'Struts': ['Action / form', 'Action mapping configuration', 'JSP/templated view', 'Service / DAO'],
    'JSF': ['Facelets view', 'Backing bean', 'Service / domain', 'Persistence layer'],
    'JDBC': ['Connection/DataSource', 'DAO or repository', 'PreparedStatement / mapping', 'Transactions'],
}

def _compiled(patterns):
    return [re.compile(p,re.I|re.M) for p in patterns]

COMPILED_FW = {key:_compiled(value[2]) for key,value in FRAMEWORKS.items()}
COMPILED_DB = {key:_compiled(value[1]) for key,value in DATABASES.items()}

def _classify_file(path, snippet):
    suffix=Path(path).suffix.lower()
    if suffix in ('.as','.mxml','.css','.js','.ts','.tsx','.jsx','.vue','.html'):
        return 'FE'
    if suffix=='.java':return 'BE'
    if suffix=='.sql':return 'DB'
    if suffix in ('.xml','.properties','.yaml','.yml','.jsp','.jspx'):
        if re.search(r'<mapper\b|<sqlMap\b|<hibernate-mapping\b',snippet,re.I):return 'DB/BE'
        if suffix in ('.jsp','.jspx'):return 'FE (server-rendered)'
    return 'SHARED/UNKNOWN'


def _object_kind(path,source,layer):
    kinds=[]
    for target,name,rule in OBJECT_RULES:
        if target in layer and re.search(rule,Path(path).name):kinds.append(name)
    if layer=='BE':
        for annot,name in [('RestController','Controller / Endpoint'),('Controller','Controller / Endpoint'),('Service','Service'),('Repository','Repository / DAO / Mapper'),('Entity','Entity / DTO / Domain'),('Mapper','Repository / DAO / Mapper')]:
            if re.search(r'@'+annot+r'\b',source) and name not in kinds:kinds.append(name)
    if layer=='FE' and path.endswith('.mxml') and 'View / Screen' not in kinds:kinds.append('View / Component')
    if re.search(r'\bRemoteObject\b|\bHTTPService\b|\bWebService\b',source) and 'Remote / Data Service' not in kinds:kinds.append('Remote / Data Service')
    if layer=='DB' and path.endswith('.sql'):kinds.append('SQL / Schema')
    return kinds or ['Unclassified source object']


def _reference_matches(framework, expected_role, objects):
    """Attach source objects to a reference role only with grounded role evidence.

    A filename, detected object role, or source framework signature can support
    a candidate, but a framework dependency by itself cannot manufacture code.
    """
    role=expected_role.lower()
    categories=[]
    if any(x in role for x in ('controller','endpoint','action / form')):
        categories=['Controller / Endpoint','Event / Controller']
    elif any(x in role for x in ('repository','dao','mapper interface')):
        categories=['Repository / DAO / Mapper']
    elif 'mapper xml' in role or 'annotation sql' in role:
        categories=['Mapper XML']
    elif any(x in role for x in ('service','business rules','service / domain')):
        categories=['Service','Remote / Data Service']
    elif any(x in role for x in ('view','component','mxml','facelets','jsp','ui ')):
        categories=['View / Screen','View / Component']
    elif any(x in role for x in ('event handler','presenter')):
        categories=['Event / Controller']
    elif any(x in role for x in ('entity','dto','model','domain','value object')):
        categories=['Entity / DTO / Domain','Model / Value Object']
    elif any(x in role for x in ('configuration','injection','bootstrap','startup','application descriptor','data-source','datasource','sqlsession','persistence')):
        categories=['Configuration / Security']
    elif 'remote' in role or 'proxy' in role:
        categories=['Remote / Data Service']
    elif 'transaction' in role:
        categories=[]
    elif 'preparedstatement' in role or 'connection/' in role:
        categories=['Repository / DAO / Mapper']
    matches=[]
    for obj in objects:
        filename=obj['file'].lower()
        if framework in ('Apache Flex','Adobe AIR') and obj['layer']!='FE':continue
        if framework not in ('Apache Flex','Adobe AIR') and obj['layer'] not in ('BE','DB/BE'):continue
        if any(r in obj['roles'] for r in categories):
            matches.append(obj['file'])
        elif 'mapper xml' in role and filename.endswith('mapper.xml'):
            matches.append(obj['file'])
        elif 'application descriptor' in role and filename.endswith('application.xml'):
            matches.append(obj['file'])
    return sorted(set(matches))


# Stable diagram palette; intended to distinguish static layers, not confidence.
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
    """Deterministic, edge-aware ordering (not a runtime dependency assertion)."""
    names = list(groups)
    if lane_mode:
        lanes = ('FE', 'BE', 'DB', 'SHARED')
        return [(lane, [n for n in names if _diagram_layer(n) == lane]) for lane in lanes]
    if reference:
        grouped = {}
        for name in names:
            framework = name.split(': ', 1)[0] if ': ' in name else '(Unmatched)'
            grouped.setdefault(framework, []).append(name)
        return list(grouped.items())
    # Sort connected nodes close together within each diagram, without falsely adding edges.
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
            neighbors = sorted((n for n in adjacency[curr] if n in remaining),
                               key=lambda n: (-adjacency[curr][n], n))
            queue.extend(neighbors)
    return [('Components', ordered)]


def _draw(path, heading, groups, links, descriptions=None, reference=False, lane_mode=False):
    """Editable left-to-right lane/framework layout with visible edges and stable grouping."""
    root = ET.Element('mxfile', {'host': 'app.diagrams.net', 'type': 'device'})
    diagram = ET.SubElement(root, 'diagram', {'id': 'stack', 'name': heading})
    columns = _ordered_components(groups, links, reference=reference, lane_mode=lane_mode)
    columns = [(title, items) for title, items in columns if items]
    if not columns:
        columns = [('Unclassified', list(groups))]
    box_w, box_h, gap_y = 470, 154, 54
    lane_w, lane_gap = 520, 90
    top = 150
    max_rows = max(len(items) for _, items in columns)
    total_width = max(1600, 100 + len(columns) * (lane_w + lane_gap))
    total_height = max(1100, top + max_rows * (box_h + gap_y) + 90)
    model = ET.SubElement(diagram, 'mxGraphModel', {
        'dx': '1400', 'dy': '900', 'grid': '1', 'gridSize': '10', 'page': '1',
        'pageWidth': str(total_width), 'pageHeight': str(total_height)
    })
    cells = ET.SubElement(model, 'root')
    ET.SubElement(cells, 'mxCell', {'id': '0'})
    ET.SubElement(cells, 'mxCell', {'id': '1', 'parent': '0'})
    ids = {}
    for col, (section, items) in enumerate(columns):
        x = 60 + col * (lane_w + lane_gap)
        layer = section if lane_mode else _diagram_layer(section)
        fill, border = LAYER_COLORS.get(layer, LAYER_COLORS['SHARED'])
        # Section header is documentation, not an application object.
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
            count = meta.get('count', 0)
            examples = meta.get('examples', [])[:3]
            label = f'{name}\n{count} source objects'
            if examples:
                label += '\n' + '\n'.join(examples)
            elif meta.get('informational'):
                label = meta['informational']
            if descriptions and name in descriptions:
                label += '\n' + descriptions[name][:70]
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
    edge_style = ('edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;'
                  'jettySize=auto;html=0;endArrow=block;endFill=1;endSize=24;'
                  'strokeWidth=3;strokeColor=#63758a;fontSize=14;'
                  'labelBackgroundColor=#ffffff;')
    if reference:
        edge_style += 'dashed=1;dashPattern=8 5;strokeColor=#888888;'
    for i, ((source, target), n) in enumerate(sorted(links.items(), key=lambda item: (-item[1], item[0]))[:180]):
        if source not in ids or target not in ids or source == target:
            continue
        edge = ET.SubElement(cells, 'mxCell', {
            'id': f'e{i+1000}', 'value': 'Reference only' if reference else f'{n} static refs',
            'style': edge_style, 'source': ids[source], 'target': ids[target],
            'edge': '1', 'parent': '1'
        })
        ET.SubElement(edge, 'mxGeometry', {'relative': '1', 'as': 'geometry'})
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)


def export_stack_architecture(repo:Repo,out,graph=None,verbose=True):
    """Reuse architecture graph and sample framework/DB evidence from eligible sources."""
    dest=Path(out).expanduser().resolve();dest.mkdir(parents=True,exist_ok=True)
    middle=_middle_dir(dest)
    graph=graph or load_architecture(repo,dest)
    if graph is None:raise ValueError('architecture graph missing or stale; run architecture first')
    framework_hits=defaultdict(list);db_hits=defaultdict(list)
    objects=[];layers=Counter();roles=defaultdict(Counter);module_layers=defaultdict(Counter)
    path_to_layer={};path_to_role={};source_read_errors=[]
    deps=graph.get('dependencies',[])
    # Dependency evidence alone never proves a framework is instantiated at runtime.
    for dependency in deps:
        lib=dependency['library'].lower()
        for key,(layer,needles,_,_) in FRAMEWORKS.items():
            if any(n in lib for n in needles):framework_hits[key].append({'source':dependency['declared_in'],'kind':'declared-dependency','match':dependency['library']})
        for key,(needles,_) in DATABASES.items():
            if any(n in lib for n in needles):db_hits[key].append({'source':dependency['declared_in'],'kind':'declared-driver','match':dependency['library']})
    # Read only files in scanner snapshot; not via Qwen. Limit local details per file.
    for path,_,_ in graph['source_inventory']:
        try:
            source=repo._read(repo._safe(path))
        except (OSError,ValueError) as exc:
            source_read_errors.append({'path':path,'error':str(exc)[:160]});continue
        layer=_classify_file(path,source)
        path_to_layer[path]=layer;layers[layer]+=1;module_layers[_module(path)][layer]+=1
        detected=_object_kind(path,source,layer)
        primary=detected[0];path_to_role[path]=primary
        roles[layer][primary]+=1
        obj={'file':path,'module':_module(path),'layer':layer,'roles':detected,
             'frameworks':[], 'evidence':[]}
        for key,regexes in COMPILED_FW.items():
            for rx in regexes:
                m=rx.search(source)
                if m:
                    line=source.count('\n',0,m.start())+1
                    evidence={'source':f'{path}:{line}','kind':'source-pattern','match':m.group(0)[:90]}
                    if len(framework_hits[key])<120:framework_hits[key].append(evidence)
                    obj['frameworks'].append(key);obj['evidence'].append(evidence)
                    break
        # configuration properties also identify a database, never infer DB from plain SQL syntax
        for key,regexes in COMPILED_DB.items():
            for rx in regexes:
                match=rx.search(source)
                if match:
                    line=source.count('\n',0,match.start())+1
                    if len(db_hits[key])<100:db_hits[key].append({'source':f'{path}:{line}','kind':'source-pattern','match':match.group(0)[:90]})
                    break
        if len(objects)<20000:objects.append(obj)
    classified={}
    for key,(layer,_,_,url) in FRAMEWORKS.items():
        hits=framework_hits[key]
        if hits:classified[key]={'layer':layer,'confidence':'source-signature' if any(h['kind']=='source-pattern' for h in hits) else 'declared-dependency-only',
                   'evidence':hits[:15],'evidence_count':len(hits),'reference':url,
                   'expected_objects':REFERENCE_STRUCTURE.get(key,[])}
    dbs={key:{'confidence':'connection-string-or-driver' if any(h['kind']=='source-pattern' for h in hits) else 'driver-dependency-only',
              'evidence':hits[:12],'evidence_count':len(hits)} for key,hits in db_hits.items() if hits}
    observed=defaultdict(Counter);links=defaultdict(Counter)
    for e in graph.get('edges',[]):
        src,dst=e['from'],e['to']
        sl,dl=path_to_layer.get(src),path_to_layer.get(dst)
        if sl and dl and sl==dl and sl in ('FE','BE','DB/BE'):
            a,b=path_to_role[src],path_to_role[dst]
            if a!=b:links[sl][a,b]+=1
        if sl and dl and sl!=dl:observed[sl][dl]+=1
    for layer,name in [('FE','frontend_architecture.drawio'),('BE','backend_architecture.drawio')]:
        groups={key:{'count':count} for key,count in roles[layer].most_common(28)}
        if not groups:groups={'No confirmed '+layer+' source':{'count':0}}
        _draw(dest/name,layer+' observed static architecture',groups,links[layer])
    # Reference expectations must be linked to real project objects. Missing
    # objects are recorded in JSON/Markdown, rather than displayed as 0-object
    # components or fictional implementation nodes.
    reference_coverage={}
    for layer,filename in [('FE','frontend_reference.drawio'),('BE','backend_reference.drawio')]:
        matched_nodes={}
        reference_edges=Counter()
        for framework,info in classified.items():
            if info['layer']!=layer:continue
            found_in_framework=[]
            for expected in info['expected_objects']:
                matches=_reference_matches(framework,expected,objects)
                key=f'{framework}: {expected}'
                reference_coverage[key]={'layer':layer,'framework':framework,'expected_role':expected,
                                         'objects':matches,'status':'found' if matches else 'not_found'}
                if matches:
                    matched_nodes[key]={'count':len(matches),'examples':matches[:3]}
                    found_in_framework.append(key)
            # Dashed edges are conceptual sequence only within one framework.
            for previous,current in zip(found_in_framework,found_in_framework[1:]):
                reference_edges[previous,current]=1
        if matched_nodes:
            _draw(dest/filename,layer+' framework roles backed by source objects',
                  dict(list(matched_nodes.items())[:60]),reference_edges,reference=True)
        else:
            _draw(dest/filename,layer+' no matched framework role objects',
                  {'No matching source objects':{'informational':'No framework reference roles mapped to source files'}},
                  Counter(),reference=False)
    # Combined diagram is intentionally a module-level link graph, not invented HTTP calls.
    combined={key:{'count':value} for key,value in layers.items() if value}
    link_counts=Counter()
    for src,targets in observed.items():
        for dst,count in targets.items():link_counts[src,dst]=count
    _draw(dest/'fe_be_architecture.drawio','Observed FE BE DB static relationships',combined or {'None':{'count':0}},link_counts,lane_mode=True)
    result={'layers':dict(layers),'module_layers':{k:dict(v) for k,v in module_layers.items()},
            'frameworks':classified,'databases':dbs,'objects':objects,
            'reference_role_coverage':reference_coverage,
            'roles':{key:dict(value) for key,value in roles.items()},
            'cross_layer_static_edges':{a+' -> '+b:n for (a,b),n in link_counts.items()},
            'read_errors':source_read_errors,
            'graph_version':graph.get('architecture_version'),
            'limitations':['No runtime invocation graph','Do not assume root-level Maven dependencies belong to every module',
                           'No DB detected is not proof that DB is absent','Object roles are naming and annotation heuristics'],
            'reference_urls':{k:v['reference'] for k,v in classified.items()}}
    (middle/'stack_architecture.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    report=['# FE / BE / Database — Framework & Architecture Analysis','',
            '> **Observed** = evidence in source; **Expected** = framework guidance. Static imports do not prove runtime calls.','',
            '## Mục lục','', '- [Phân loại FE BE DB](#phân-loại-fe-be-db)',
            '- [Framework và bằng chứng](#framework-và-bằng-chứng)',
            '- [Database](#database)', '- [Objects và cấu trúc khuyến nghị](#objects-và-cấu-trúc-khuyến-nghị)',
            '- [Sơ đồ](#sơ-đồ)', '- [Giới hạn](#giới-hạn)','',
            '## Phân loại FE BE DB','',
            '| Nhóm | File nguồn nhận diện |','|---|---:|']
    for k,n in layers.most_common():report.append(f'| {k} | {n} |')
    report+=['','### FE/BE/DB trong từng module','',
             '| Module | FE | BE | DB | Shared / Unknown |','|---|---:|---:|---:|---:|']
    for module, counts in sorted(module_layers.items()):
        report.append(f'| `{module}` | {counts["FE"]+counts["FE (server-rendered)"]} | {counts["BE"]} | {counts["DB"]+counts["DB/BE"]} | {counts["SHARED/UNKNOWN"]} |')
    report+=['','## Framework và bằng chứng','', '| Framework | Layer | Độ xác nhận | Bằng chứng |','|---|---|---|---|']
    for name,info in classified.items():
        examples=', '.join('`'+h['source']+'`' for h in info['evidence'][:3])
        report.append(f'| [{name}]({info["reference"]}) | {info["layer"]} | {info["confidence"]} | {examples} |')
    if not classified:report.append('| Chưa tìm thấy theo bộ pattern hiện tại | | | |')
    report+=['','## Database','', '| Database | Mức bằng chứng | Vị trí |','|---|---|---|']
    for name,info in dbs.items():report.append(f'| {name} | {info["confidence"]} | '+', '.join('`'+h['source']+'`' for h in info['evidence'][:3])+' |')
    if not dbs:report.append('| Chưa xác định driver/connection URL | Không kết luận không có DB | |')
    report+=['','## Objects và cấu trúc khuyến nghị','',
            '| Layer | Object role quan sát được | Số file |','|---|---|---:|']
    for layer,mapping in roles.items():
        for role,n in mapping.most_common(30):report.append(f'| {layer} | {role} | {n} |')
    for name,info in classified.items():
        report+=['',f'### {name} — Reference structure','',
                 'Đây là cấu trúc **tham khảo**, không có nghĩa mọi object đã tồn tại trong source.','']
        report.extend('- '+item for item in info['expected_objects'])
        report.append(f'- Tài liệu: {info["reference"]}')
    report+=['','### Đối chiếu Reference với source','',
             '| Framework | Vai trò tham khảo | Object tìm thấy | File minh họa |',
             '|---|---|---:|---|']
    for item in reference_coverage.values():
        examples=', '.join('`'+x+'`' for x in item['objects'][:2]) or 'Không tìm thấy trong source đã quét'
        report.append(f'| {item["framework"]} | {item["expected_role"]} | {len(item["objects"])} | {examples} |')
    report+=['','## Sơ đồ','',
             '- `frontend_architecture.drawio`: FE objects được nhận diện và quan hệ tĩnh giữa các vai trò.',
             '- `backend_architecture.drawio`: BE objects được nhận diện và quan hệ tĩnh giữa các vai trò.',
             '- `fe_be_architecture.drawio`: liên hệ FE / BE / DB chỉ khi có cạnh tĩnh từ source.',
             '- `frontend_reference.drawio`, `backend_reference.drawio`: chỉ các vai trò tham khảo **tìm được file tương ứng**; các vai trò không tìm được được liệt kê trong bảng Markdown và JSON, không vẽ ô rỗng.',
             '- Chi tiết machine-readable: `middle-files/stack_architecture.json`.','',
             '## Giới hạn','',
             '- FE/BE được phân theo extension / source signatures; thư mục chứa cả hai có thể là mixed.',
             '- Framework được xác định bằng dependency hoặc pattern cú pháp; không phải chứng cứ framework đã active ở runtime.',
             '- Database từ driver hoặc URL JDBC, không thể biết DB thật đang được dùng nếu thiếu runtime config.',
             '- Sơ đồ không vẽ đường FE → HTTP → BE → DB nếu chỉ có kiến thức thông thường mà chưa có source reference.',
             '- Không phán đoán object thiếu khi phân tích không đầy đủ; không tự generate code mới.',
             '- Chỉ scanner-supported source nhỏ hơn 1 MB, không đọc binary hay thư viện đóng gói.']
    (dest/'stack_architecture.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
    if verbose:print('[Stack] FE/BE/DB framework evidence and diagrams generated.',flush=True)
    return {'stack_report':str(dest/'stack_architecture.md'),
            'fe_diagram':str(dest/'frontend_architecture.drawio'),
            'be_diagram':str(dest/'backend_architecture.drawio'),
            'fe_reference':str(dest/'frontend_reference.drawio'),
            'be_reference':str(dest/'backend_reference.drawio'),
            'fe_be_diagram':str(dest/'fe_be_architecture.drawio'),
            'stack_json':str(middle/'stack_architecture.json'),
            'frameworks_detected':list(classified), 'databases_detected':list(dbs)}
