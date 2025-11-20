// Some definitions presupposed by pandoc's typst output.
#let blockquote(body) = [
  #set text( size: 0.92em )
  #block(inset: (left: 1.5em, top: 0.2em, bottom: 0.2em))[#body]
]

#let horizontalrule = line(start: (25%,0%), end: (75%,0%))

#let endnote(num, contents) = [
  #stack(dir: ltr, spacing: 3pt, super[#num], contents)
]

#show terms: it => {
  it.children
    .map(child => [
      #strong[#child.term]
      #block(inset: (left: 1.5em, top: -0.4em))[#child.description]
      ])
    .join()
}

// Some quarto-specific definitions.

#show raw.where(block: true): set block(
    fill: luma(230),
    width: 100%,
    inset: 8pt,
    radius: 2pt
  )

#let block_with_new_content(old_block, new_content) = {
  let d = (:)
  let fields = old_block.fields()
  fields.remove("body")
  if fields.at("below", default: none) != none {
    // TODO: this is a hack because below is a "synthesized element"
    // according to the experts in the typst discord...
    fields.below = fields.below.abs
  }
  return block.with(..fields)(new_content)
}

#let empty(v) = {
  if type(v) == str {
    // two dollar signs here because we're technically inside
    // a Pandoc template :grimace:
    v.matches(regex("^\\s*$")).at(0, default: none) != none
  } else if type(v) == content {
    if v.at("text", default: none) != none {
      return empty(v.text)
    }
    for child in v.at("children", default: ()) {
      if not empty(child) {
        return false
      }
    }
    return true
  }

}

// Subfloats
// This is a technique that we adapted from https://github.com/tingerrr/subpar/
#let quartosubfloatcounter = counter("quartosubfloatcounter")

#let quarto_super(
  kind: str,
  caption: none,
  label: none,
  supplement: str,
  position: none,
  subrefnumbering: "1a",
  subcapnumbering: "(a)",
  body,
) = {
  context {
    let figcounter = counter(figure.where(kind: kind))
    let n-super = figcounter.get().first() + 1
    set figure.caption(position: position)
    [#figure(
      kind: kind,
      supplement: supplement,
      caption: caption,
      {
        show figure.where(kind: kind): set figure(numbering: _ => numbering(subrefnumbering, n-super, quartosubfloatcounter.get().first() + 1))
        show figure.where(kind: kind): set figure.caption(position: position)

        show figure: it => {
          let num = numbering(subcapnumbering, n-super, quartosubfloatcounter.get().first() + 1)
          show figure.caption: it => {
            num.slice(2) // I don't understand why the numbering contains output that it really shouldn't, but this fixes it shrug?
            [ ]
            it.body
          }

          quartosubfloatcounter.step()
          it
          counter(figure.where(kind: it.kind)).update(n => n - 1)
        }

        quartosubfloatcounter.update(0)
        body
      }
    )#label]
  }
}

// callout rendering
// this is a figure show rule because callouts are crossreferenceable
#show figure: it => {
  if type(it.kind) != str {
    return it
  }
  let kind_match = it.kind.matches(regex("^quarto-callout-(.*)")).at(0, default: none)
  if kind_match == none {
    return it
  }
  let kind = kind_match.captures.at(0, default: "other")
  kind = upper(kind.first()) + kind.slice(1)
  // now we pull apart the callout and reassemble it with the crossref name and counter

  // when we cleanup pandoc's emitted code to avoid spaces this will have to change
  let old_callout = it.body.children.at(1).body.children.at(1)
  let old_title_block = old_callout.body.children.at(0)
  let old_title = old_title_block.body.body.children.at(2)

  // TODO use custom separator if available
  let new_title = if empty(old_title) {
    [#kind #it.counter.display()]
  } else {
    [#kind #it.counter.display(): #old_title]
  }

  let new_title_block = block_with_new_content(
    old_title_block, 
    block_with_new_content(
      old_title_block.body, 
      old_title_block.body.body.children.at(0) +
      old_title_block.body.body.children.at(1) +
      new_title))

  block_with_new_content(old_callout,
    block(below: 0pt, new_title_block) +
    old_callout.body.children.at(1))
}

// 2023-10-09: #fa-icon("fa-info") is not working, so we'll eval "#fa-info()" instead
#let callout(body: [], title: "Callout", background_color: rgb("#dddddd"), icon: none, icon_color: black, body_background_color: white) = {
  block(
    breakable: false, 
    fill: background_color, 
    stroke: (paint: icon_color, thickness: 0.5pt, cap: "round"), 
    width: 100%, 
    radius: 2pt,
    block(
      inset: 1pt,
      width: 100%, 
      below: 0pt, 
      block(
        fill: background_color, 
        width: 100%, 
        inset: 8pt)[#text(icon_color, weight: 900)[#icon] #title]) +
      if(body != []){
        block(
          inset: 1pt, 
          width: 100%, 
          block(fill: body_background_color, width: 100%, inset: 8pt, body))
      }
    )
}


// This is an example typst template (based on the default template that ships
// with Quarto). It defines a typst function named 'article' which provides
// various customization options. This function is called from the 
// 'typst-show.typ' file (which maps Pandoc metadata function arguments)
//
// If you are creating or packaging a custom typst template you will likely
// want to replace this file and 'typst-show.typ' entirely. You can find 
// documentation on creating typst templates and some examples here: 
//   - https://typst.app/docs/tutorial/making-a-template/
//   - https://github.com/typst/templates


#let article(
  title: none,
  subtitle: none,
  authors: none,
  date: none,
  institut: none,
  keywords: none,
  confidential: false,
  thesis-type: none,
  degree-type: none,
  study-year: none,
  submission-date: none,
  study-direction: none,
  supervisors: none,
  cover-image: none,
  abstract: none,
  abstract-title: none,
  cols: 1,
  margin: (x: 1.25in, y: 2cm),
  paper: "us-letter",
  lang: "en",
  region: "US",
  font: ("Arial", "Helvetica Neue", "Helvetica", "Liberation Sans", "DejaVu Sans", "Noto Sans"),
  fontsize: 11pt,
  title-size: 1.5em,
  subtitle-size: 1.25em,
  heading-family: "libertinus serif",
  heading-weight: "bold",
  heading-style: "normal",
  heading-color: black,
  heading-line-height: 0.65em,
  sectionnumbering: none,
  number-depth: none,
  pagenumbering: "1",
  toc: false,
  toc_title: none,
  toc_depth: none,
  toc_indent: 1.5em,
  doc,
) = {
  set page(
    paper: paper,
    margin: margin,
    numbering: none,
  )
  set par(justify: true)
  set text(lang: lang,
           region: region,
           font: font,
           size: fontsize)
  set heading(
    numbering: if sectionnumbering != none {
      (..nums) => if nums.pos().len() <= number-depth {
        numbering(sectionnumbering, ..nums)
      }
    } else { none }
  )
  // State to track if we're in appendix mode
  let appendix-mode = state("appendix-mode", false)
  
  show heading: it => {
    it
    v(0.5em)
  }
  // Pagebreaks are handled by Lua filter to avoid container conflicts
  
  // Title page
  if title != none or authors != none {
    page(numbering: none)[
      #align(center)[
        #if lang == "en" [
          ZURICH UNIVERSITY OF APPLIED SCIENCES \
          DEPARTEMENT LIFE SCIENCES AND FACILITY MANAGEMENT
        ] else [
          ZÜRCHER HOCHSCHULE FÜR ANGEWANDTE WISSENSCHAFTEN \
          DEPARTEMENT LIFE SCIENCES UND FACILITY MANAGEMENT
        ]
        #if institut != none [
          \ #upper(institut)
        ]
      ]
      #v(1fr)
      #if title != none {
        align(center)[#block(inset: 2em)[
          #set par(leading: heading-line-height)
          #text(weight: "bold", size: title-size)[#title]
          #if subtitle != none {
            parbreak()
            text(weight: "bold", size: subtitle-size)[#subtitle]
          }
          #if cover-image != none {
            v(0.5cm)
            image(cover-image.src, width: eval(cover-image.max-width), height: eval(cover-image.max-height), fit: "contain")
            v(0.1cm)
          }
          #if confidential {
            parbreak()
            if lang == "en" [
              #text(weight: "bold", size: subtitle-size)[confidential]
            ] else [
              #text(weight: "bold", size: subtitle-size)[vertraulich]
            ]
          }
          #if thesis-type != none {
            v(0.2cm)
            text(weight: "bold", size: subtitle-size)[#thesis-type]
          }
        ]]
      }

      #v(0.5cm)

      #if authors != none {
        align(center)[
          #if lang == "en" [
            by \
          ] else [
            von \
          ]
          #for author in authors [
            #author.name \
          ]
          #if degree-type != none and study-year != none [
            \ #degree-type #study-year
          ]
          #if submission-date != none [
            \ #if lang == "en" [
              Submission date #submission-date
            ] else [
              Abgabedatum #submission-date
            ]
          ]
          #if study-direction != none [
            \ Studienrichtung #study-direction
          ]
        ]
      }

      #v(1fr)
      
      #if supervisors != none {
        align(left)[
          #if lang == "en" [
            *Supervisors:* \
          ] else [
            *Betreuer / Betreuerinnen:* \
          ]
          #for supervisor in supervisors [
            #if supervisor.title != none [#supervisor.title] #supervisor.name \
            #supervisor.affiliation \
            \
          ]
        ]
      }
    ]
  }

  // Imprint page (second page)
  if title != none or authors != none {
    page(numbering: none)[
      #v(1fr)
      
      #align(left)[
        #if lang == "en" [
          *Imprint*
        ] else [
          *Impressum*
        ]
      ]
      
      #v(2em)
      
      // Citation section
      #if authors != none and title != none {
        align(left)[
          #if lang == "en" [
            *Recommended Citation:*
          ] else [
            *Zitiervorschlag:*
          ]
        ]
        
        align(left)[
          #text(size: 10pt)[
            #for author in authors [
              #author.name
              #if author != authors.last() [, ]
            ]
            #if date != none [(#date). ] else if submission-date != none [(#{
              let date-str = repr(submission-date).trim("[").trim("]")
              let year = date-str.split("-").at(0)
              year
            }). ] else [(n.d.). ]
            #emph[#title#if subtitle != none [: #subtitle]]. 
            #if institut != none {
              if lang == "en" [
                Zurich University of Applied Sciences, Department Life Sciences and Facility Management, #institut.
              ] else [
                Zürcher Hochschule für Angewandte Wissenschaften, Departement Life Sciences und Facility Management, #institut.
              ]
            }
          ]
        ]
        
        v(2em)
      }
      
      // Keywords
      #if keywords != none {
        align(left)[
          #if lang == "en" [
            *Keywords:* #keywords
          ] else [
            *Schlagworte:* #keywords
          ]
        ]
        v(2em)
      }
      
      // Institute
      #if institut != none {
        align(left)[
          #if lang == "en" [
            #institut \
            Department Life Sciences and Facility Management \
            Zurich University of Applied Sciences
          ] else [
            #institut \
            Departement Life Sciences und Facility Management \
            Zürcher Hochschule für Angewandte Wissenschaften
          ]
        ]
      }
    ]
  }

  // Start page numbering for main content with header
  set page(
    numbering: pagenumbering,
    header: [
      #text(size: 0.8em)[
        #grid(
          columns: (1fr, 1fr, 1fr),
          align: (left, center, right),
          gutter: 1em,
          [ZHAW LSFM],
          [#if thesis-type != none [#thesis-type]],
          [#if authors != none [
            #for author in authors [
              #author.name
              #if author != authors.last() [, ]
            ]
          ]]
        )
      ]
      #v(0.3em)
      #line(length: 100%, stroke: 0.5pt)
    ],
    footer: [
      #text(size: 0.8em)[
        #align(center)[
          #context counter(page).display()
        ]
      ]
    ]
  )
  counter(page).update(1)

  if abstract != none {
    block(inset: 2em)[
    #text(weight: "semibold")[#abstract-title] #h(1em) #abstract
    ]
  }

  if toc {
    let title = if toc_title == none {
      auto
    } else {
      toc_title
    }
    block(above: 0em, below: 2em)[
    #outline(
      title: toc_title,
      depth: toc_depth,
      indent: toc_indent
    );
    ]
  }

  if cols == 1 {
    doc
  } else {
    columns(cols, doc)
  }
}

#set table(
  inset: 6pt,
  stroke: none
)

#set page(
  paper: "us-letter",
  margin: (x: 1.25in, y: 1.25in),
  numbering: "1",
)


// Typst custom formats typically consist of a 'typst-template.typ' (which is
// the source code for a typst template) and a 'typst-show.typ' which calls the
// template's function (forwarding Pandoc metadata values as required)
//
// This is an example 'typst-show.typ' file (based on the default template  
// that ships with Quarto). It calls the typst function named 'article' which 
// is defined in the 'typst-template.typ' file. 
//
// If you are creating or packaging a custom typst template you will likely
// want to replace this file and 'typst-template.typ' entirely. You can find
// documentation on creating typst templates here and some examples here:
//   - https://typst.app/docs/tutorial/making-a-template/
//   - https://github.com/typst/templates
#show: doc => article(
  title: [Modelling Wildlife Corridors: Spatial Analysis of Topographic and Landscape Barriers to determine Ecological Connectivity],
  subtitle: [Project Work 2],
  authors: (
    ( name: [Lukas Buchmann],
      affiliation: [],
      email: [] ),
    ),
  institut: [INSTITUT FÜR COMPUTATIONAL LIFE SCIENCES],
  keywords: [Wildlife Corridors, Connectivity Modeling, Ecological Connectivity, Least-Cost Path (LCP) Analysis, Spatial Analysis],
  thesis-type: [Projekt Work 2],
  degree-type: [Bachelor's degree program],
  study-year: [2025],
  submission-date: [2025-12-11],
  study-direction: [Applied Digital Life Sciences (ADLS)],
  supervisors: (
    (
      title: [],
      name: [Ratnaweera Nils],
      affiliation: [ZHAW Life Sciences und Facility Management, Wädenswil],
    ),
  ),
  cover-image: (
    src: "cover.png",
    max-width: "100%",
    max-height: "5cm",
  ),
  lang: "en",
  sectionnumbering: "1.1.",
  number-depth: 2,
  pagenumbering: "1",
  toc_title: [Table of contents],
  toc_depth: 2,
  cols: 1,
  doc,
)

#pagebreak(weak: true)
#block[
#heading(
level: 
1
, 
numbering: 
none
, 
outlined: 
false
, 
[
Zusammenfassung
]
)
]
Diese Arbeit untersucht die Beziehung zwischen Gehirngröße und Körpergewicht bei verschiedenen Säugetierarten anhand des MASS::Animals Datensatzes. Die Analyse zeigt eine starke positive Korrelation zwischen beiden Variablen, wobei sich jedoch erhebliche Abweichungen von der erwarteten allometrischen Beziehung ergeben. Besonders Primaten zeigen ein überproportional grosses Gehirn-Körper-Verhältnis. Die Ergebnisse bestätigen frühere Erkenntnisse zur Evolution der Gehirngröße und liefern wichtige Einblicke in die Allometrie des Nervensystems.

#pagebreak(weak: true)
#block[
#heading(
level: 
1
, 
numbering: 
none
, 
outlined: 
false
, 
[
Inhaltsverzeichnis
]
)
]
#outline(title: none, depth: 2)
#pagebreak(weak: true)
#block[
#heading(
level: 
1
, 
numbering: 
none
, 
[
Liste der Abkürzungen
]
)
]
#table(
  columns: (13.89%, 48.61%),
  align: (auto,auto,),
  [MASS], [Modern Applied Statistics with S],
  [log], [natürlicher Logarithmus],
  [R²], [Bestimmtheitsmass],
  [kg], [Kilogramm],
  [g], [Gramm],
)
#pagebreak(weak: true)
= Introduction
<introduction>
== 1.1 The Challenge of Habitat Fragmentation
<the-challenge-of-habitat-fragmentation>
Across Europe, landscapes are undergoing rapid transformation driven by the expansion of transportation infrastructure, urban sprawl, and the intensification of agriculture (European Environment Agency, 2024). This process leads to habitat fragmentation: the division of large, continuous habitats into smaller, more isolated patches. Fragmentation is recognized as a primary driver of global biodiversity loss (Haddad et al., 2015). Its ecological consequences are severe: it limits wildlife mobility, isolates populations, and restricts gene flow (Kuehn et al., 2007; Wang et al., 2016). This, in turn, can lead to inbreeding, a loss of adaptive genetic diversity, and reduced long-term population resilience, making populations more vulnerable to local extinction (Haddad et al., 2015; Kuehn et al., 2007).

The situation in Switzerland is particularly acute (Jaeger, 2007; Jaeger et al., 2011). The Swiss Federal Office for the Environment (FOEN) has identified fragmentation from artificial barriers as a key pressure on biodiversity (FOEN, 2010; Jaeger et al., 2011). This fragmentation is most severe in the Swiss Central Lowlands (FOEN, 2010). A comprehensive study by the Swiss Federal Institute for Forest, Snow and Landscape Research (WSL) identified the Canton of Schaffhausen as one of the eight most fragmented cantons in the country, underscoring the urgent need for regional connectivity planning (Jaeger, 2007).

== 1.2 The Role of Ecological Connectivity
<the-role-of-ecological-connectivity>
To counteract these effects, conservation efforts increasingly focus on maintaining and restoring ecological connectivity, defined as the unimpeded movement of species and the flow of natural processes that sustain life. A primary tool for achieving this is the identification and protection of wildlife corridors. These are linear landscape elements that link otherwise isolated habitat patches. By facilitating animal movement, corridors are essential for enabling dispersal, maintaining genetic diversity, and allowing species to migrate in response to seasonal needs or long-term climate change (Hilty et al., 2020).

== 1.3 Focal Species: The Roe Deer (Capreolus capreolus)
<focal-species-the-roe-deer-capreolus-capreolus>
The successful planning of such corridors depends on a species-specific approach (Beier et al., 2008). This project focuses on the roe deer (Capreolus capreolus), an ideal focal species for connectivity modelling in the Swiss landscape. As one of Europe's most common wild ungulates, the roe deer is highly adaptable. It demonstrates significant behavioral flexibility, inhabiting not only its traditional forest-mosaic habitats but also does well in open agricultural plains (Jepsen et al., 2012).

Despite this adaptability, roe deer are highly vulnerable to fragmentation. Transportation networks pose a dual threat: direct mortality from wildlife-vehicle collisions and the barrier effect, where high-traffic roads hinder access to critical resources (Maertz et al., 2024). This barrier effect can be as damaging as direct habitat loss, leading to the genetic isolation of populations. A study on roe deer in Central Switzerland, for example, demonstrated significant genetic differentiation between populations separated by a fenced motorway. Because roe deer are widespread, mobile, and frequently interact with infrastructure, they serve as an excellent model for assessing landscape-level connectivity for large mammals (Kuehn et al., 2007).

== 1.4 Methodology: Least-Cost Path (LCP) Analysis
<methodology-least-cost-path-lcp-analysis>
This study employs Least-Cost Path (LCP) analysis, a standard and widely used methodology in GIS-based connectivity modelling (Beier et al., 2008; Cushman et al., 2013). The LCP approach is built on the concept of a resistance surface (Cushman et al., 2013). This is a GIS raster layer where each pixel is assigned a "cost" value representing the difficulty, energy expenditure, or mortality risk a species encounters when moving through that specific landscape type (Zeller et al., 2012). This "cost" is derived from expert knowledge and ecological literature, assigning low resistance to preferred habitats and high resistance to barriers (Beier et al., 2008). The LCP algorithm then calculates the most efficient route between defined core habitat patches, the path of least cumulative resistance (Cushman et al., 2013).

== 1.5 Project Objectives
<project-objectives>
The primary objective of this project is to develop, improve, and evaluate a GIS-based connectivity model for roe deer (Capreolus capreolus) in the highly fragmented landscape of the Canton of Schaffhausen, implemented using the Python programming language.

The specific aims are to:

- Create a detailed resistance surface from the OpenStreetMap dataset.

- Perform a Least-Cost Path (LCP) analysis to compute cumulative movement costs and identify potential wildlife corridors connecting suitable habitat patches.

- Analyze the resulting model to identify and map key bottlenecks, major obstacles, and other landscape patterns that limit ecological connectivity.

The final output will be a reproducible connectivity model and a set of cartographic products. This work is intended to serve as a practical, data-driven decision-making aid for regional conservation and spatial planning.

#pagebreak(weak: true)
= Material and Methods
<material-and-methods>
== Study Area
<study-area>
The study area for this project is the Canton of Schaffhausen, located in Northern Switzerland. This region was selected specifically because it has been identified as one of the eight most fragmented cantons in the nation, primarily due to its dense transportation network and expanding settlements (Jaeger, 2007). The landscape is a heterogeneous mosaic of forests and agricultural lands, intersected by the Rhine river and human infrastructure. This environment represents a typical, pressured landscape for Central European wildlife and serves as a critical case study for connectivity modeling.

== Software and Data Acquisition
<software-and-data-acquisition>
#block[
#heading(
level: 
3
, 
numbering: 
none
, 
[
Software and Reproducibility
]
)
]
This project was conducted using the Python 3.10 programming language. It was carried out in three different steps. The first step was about, creating the resistance surface. The second step involved calculating the least cost paths between predefined points on this resistance surface. This allowed the habitats and movement corridors of the deer to be modeled and stored as georeferenced GIS data formats. The third step then aimed to analyze these GIS data formats, identify problems, and recommend solutions.

The key open-source Python libraries used for geospatial analysis included:

- GeoPandas (v. 1.0+) for vector data manipulation (clipping, buffering).

- Rasterio (v. 1.3+) for all raster operations (re-projection, rasterization, and weighted overlays).

- scikit-image (v. 0.2x) for executing the Least-Cost Path algorithm.

#block[
#heading(
level: 
3
, 
numbering: 
none
, 
[
Geospatial Datasets
]
)
]
All geospatial datasets used in this study were open-source data provided by OpenStreetMap and Corine Landcover.

#block[
#heading(
level: 
4
, 
numbering: 
none
, 
[
Primary Feature Data: OpenStreetMap (OSM)
]
)
]
The primary dataset for landscape features was derived from OpenStreetMap (OSM), a global, high-resolution, volunteered geographic information (VGI) project.

Description: OSM data provides detailed, up-to-date geospatial information on fine-scale features critical to wildlife movement, such as roads, railways, fences, buildings, land use polygons, and minor waterways.

Acquisition and Processing: Raw data was downloaded in Protocolbuffer Binary Format (.pbf) from Geofabrik GmbH, using separate files for Baden-Württemberg (Germany) and Switzerland to cover the transboundary study area. The data was extracted, combined, and clipped to the AOI using the pyrosm Python library.

Structure: The processed data was filtered to retain only features relevant to the resistance model (e.g., features tagged with highway, landuse, natural, barrier, etc.). This resulted in a single GeoPackage file containing a unified set of polygon and line string geometries for the entire study area, reprojected to the project's master CRS (e.g., EPSG:32632).

#block[
#heading(
level: 
4
, 
numbering: 
none
, 
[
Base Land Cover Data: CORINE Land Cover (CLC)
]
)
]
The secondary dataset, CORINE Land Cover (CLC) 2018, was used to provide a comprehensive, "wall-to-wall" base layer.

Description: CLC is a standardized European land cover dataset with a 100-meter resolution and a 25-hectare minimum mapping unit.

Acquisition and Processing: The raster dataset (U2018\_CLC2018\_V2020\_20u1.tif) was acquired from the Copernicus Land Monitoring Service. It was clipped to the study area's buffered bounds.

Role in Model: Due to its coarse resolution, CLC is not as accurate as OSM for defining specific features. Therefore, its primary role in this model is to act as a fallback layer, providing a generalized resistance value in any pixel where finer-scale OSM data is absent. This method ensures the final cost surface has no "NoData" gaps.

#block[
#heading(
level: 
3
, 
numbering: 
none
, 
[
Resistance Cost Datasets
]
)
]
A hybrid approach was used to create the final cost surface. Resistance values were defined in two external configuration files, osm\_resistance\_costs.csv and clc\_resistance\_costs.csv, to ensure transparency and reproducibility.

The core principle of the model is that OSM features (the primary, high-resolution data) are given precedence, while the reclassified CLC raster serves as a base map to fill any gaps.

All resistance values were assigned on a relative scale, where 1 represents optimal, cost-free movement (preferred habitat) and 5000 represents an absolute or impassable barrier. The derivation of these values is detailed in two separate configuration files, described below.

#block[
#heading(
level: 
4
, 
numbering: 
none
, 
[
clc\_resistance\_costs.csv (The Base Layer)
]
)
]
This file maps all 44 CLC Level 3 classes to an ecological resistance value.

- Structure: The CSV contains three columns: clc\_code (e.g., 311), LABEL3 (e.g., 'Broad-leaved forest'), and resistance.

- Class Selection: All 44 classes were included to ensure the reclassification of the CLC raster would be complete.

- Cost Assignment: Values were assigned based on roe deer habitat preferences from scientific literature.

  - Optimal habitats, such as 311: Broad-leaved forest and 313: Mixed forest, were assigned the lowest cost (1).

  - Permeable foraging areas, like 231: Pastures (8) and 211: Non-irrigated arable land (20), received slightly higher costs.

  - Major barriers, such as 111: Continuous urban fabric (5000) and 512: Water bodies (800), received high to impassable values.

#block[
#heading(
level: 
4
, 
numbering: 
none
, 
[
osm\_resistance\_costs.csv (The Primary Feature Layer)
]
)
]
This file defines the resistance values for the high-resolution OSM features and controls the order in which they are rasterized.

- Structure: This CSV contains four critical columns: osm\_key, osm\_value, resistance, and priority.

- Tag Selection: Tags were systematically selected based on the official OSM "Map features" wiki and their known ecological relevance. This focused the model on consistent, well-documented tags (landuse, natural, highway, waterway, barrier, railway, building) rather than ambiguous, community-added tags.

- resistance (The Ecological Cost): Values were assigned using a scientifically-defensible hierarchy:

  - Transportation Infrastructure: Costs are directly related to traffic volume and fencing, following the COST 341 framework. This creates a steep gradient from highway=track (20) to highway=tertiary (500) up to the impassable, fenced highway=motorway (5000).

  - Habitats & Land Use: Values were chosen to be consistent with the CLC layer. landuse=forest (1) is optimal habitat, while landuse=industrial (4500) is a major barrier.

  - Barriers: Specific barrier features were included, such as barrier=fence (800) and barrier=wall (1500), which represent significant (but not always absolute) obstacles.

  - priority (The Technical Parameter): This column is crucial for the model's construction. It dictates the "burn-in" order for rasterization, ensuring that features are layered correctly. For example, a low-priority polygon like landuse=forest (priority 1) is processed first. A high-priority linear feature like highway=motorway (priority 10) is processed last, allowing it to correctly "burn" its high resistance value (5000) on top of the forest pixel's value (1).

== Data Pre-processing
<data-pre-processing>
#block[
#heading(
level: 
3
, 
numbering: 
none
, 
[
Datenquelle und Charakteristika
]
)
]
Der Datensatz wurde ursprünglich von Weisberg (1980) zusammengestellt und enthält Messungen von verschiedenen Wirbeltierarten. Die Daten umfassen sowohl terrestrische als auch aquatische Säugetiere mit einem breiten Spektrum von Körpergewichten.

#block[
#heading(
level: 
3
, 
numbering: 
none
, 
[
Datenqualität und Limitationen
]
)
]
Einige Messungen stammen aus älteren Studien und könnten methodische Ungenauigkeiten aufweisen. Besonders bei sehr grossen Tieren wie Elefanten können die Gehirngewichte schwer präzise zu bestimmen sein.

== Resistance Surface
<resistance-surface>
The creation of the resistance surface is the foundational step for this project, and it is built as a modular, reproducible workflow using Python, primarily with the GeoPandas, Rasterio, and NumPy libraries. Three documents are required to execute the workflow. The `resistance_costs.csv` file, which stores the resistance costs for each landcover, water and roads type, the `gis_utils.py` file, which containes all gis, loading and plotting functions for processing the data and the `cost_surface_model.ipynb` file, which executes the workflow step by step.

The process starts with defining the study area. Because the canton of Schaffhausen has two large exclaves, it is geographically fragmented. Therefore it is insufficient to just use its base geometry. To create a contiguous study region that connects the mainland to its exclaves, first the canton's geometry is buffered by 10,000 meters. Since the project focus is exclusively on Swiss territory, this large, buffered area is then clipped to the national boundary of Switzerland, which gave the final, unified Area of Schaffhausen with connections to its exclaves. It should also be noted that the exclaves of Schaffhausen are located in Switzerland and are not completely surrounded by German territory.

In the next step, the data layers are loaded and clipped to the study area. Since the water and roads layer are linestrings, which have no area and cannot be properly represented in a 10-meter raster, they are buffered (by 5 meters) to transform them into 10-meter-wide polygons, giving them a realistic spatial footprint for a better rasterization afterwards. Then the flowing and standing water layer are combined to create a single, comprehensive water barrier layer. Because the Landcover layer from swissTLM3D and Corine Landcover have different type names, the names are harmonized in a new column called `lc_type`. This harmonization is carried out arbitrarily according to the author's understanding.

To ensure that all subsequent raster layers are perfectly aligned for analysis, the study area is used to define a "master grid." This grid serves as a non-negotiable template, establishing the spatial bounds, the 10.0-meter resolution, and the EPSG:2056 (LV95) coordinate system for every raster file which is created.

Once all vector layers are prepared, the resistance costs are assigned. Therefore the CSV file (resistance\_costs.csv) is loaded. With the map and get functions these costs are then mapped to the four main vector layers: swissTLM Landcover, CORINE Landcover, the combined Water layer, and the buffered Roads layer. Then each of these layers is "burned", with their new cost values, onto the master grid, resulting in four separate 10-meter GeoTIFFs.

The final stage is to combine these four intermediate rasters into one. This is a two-step process. First, the two landcover rasters are harmonized. The swissTLM3D raster is more detailed and is therfore used as the high-priority layer, but it has NoData gaps. However, performing a "priority-fill" using numpy.where to create a new raster (harmonized\_landcover\_type.tif) fills up these NoData gaps with the data from Corine Landcover. This function iterates pixel by pixel, using the swissTLM3D value if it is valid, but filling the pixel with the CORINE value if the swissTLM3D value is NoData.

Second, this new harmonized landcover raster is combined with the water and road rasters. For this final combination, a "maximum-value" logic is used. First, all three rasters are stacked and then, using numpy.maximum.reduce, select the highest cost value at each pixel location. This is crucial as it ensures that a high-cost feature, like a highway (cost 500), correctly overwrites the low-cost forest (cost 50) it passes through. The result of this entire workflow is the final\_resistance\_surface.tif: a single, comprehensive 10-meter raster where each pixel's value represents the ecological cost for roe deer movement, now ready for the least-cost path analysis.

#block[
#block[
Weisberg, Sanford. 1980. “Some Large-Sample Tests for Nonnormality in the Linear Regression Model: Comment.” #emph[Journal of the American Statistical Association] 75 (369): 28--31.

] <ref-weisberg1980>
] <refs>



